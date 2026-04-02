"""Revettr MCP Server — counterparty risk scoring as MCP tools.

Wraps the Revettr REST API (revettr.com) so MCP clients like
Claude Desktop, Cursor, and Windsurf can call scoring and risk
analysis tools natively.
"""

import asyncio
import ipaddress
import math
import os
import re

import httpx
from fastmcp import FastMCP

REVETTR_URL = os.getenv("REVETTR_URL", "https://revettr.com")


def _validate_url(url: str) -> None:
    """Ensure URL uses HTTPS (allow HTTP only for localhost)."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    try:
        is_local = hostname in ("localhost",) or ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        is_local = False
    if not is_local and not url.startswith("https://"):
        raise ValueError(
            f"REVETTR_URL must use HTTPS (got {url!r}). "
            "HTTP is only allowed for localhost/127.0.0.1 during development."
        )


_validate_url(REVETTR_URL)

# ---------------------------------------------------------------------------
# Flag descriptions for explain_risk
# ---------------------------------------------------------------------------

FLAG_DESCRIPTIONS: dict[str, str] = {
    "domain_age_under_30d": (
        "The domain was registered less than 30 days ago, a common indicator "
        "of fraudulent or newly created entities."
    ),
    "domain_age_under_90d": (
        "The domain was registered less than 90 days ago. Newer domains carry "
        "higher risk."
    ),
    "no_mx_records": (
        "The domain has no MX (mail) records, suggesting it may not be a "
        "legitimate business domain."
    ),
    "ssl_invalid": "The domain's SSL certificate is invalid or expired.",
    "ssl_missing": "The domain has no SSL certificate.",
    "tor_exit_node": (
        "The IP address is a Tor exit node, indicating anonymization."
    ),
    "known_vpn": "The IP address belongs to a known VPN provider.",
    "datacenter_ip": (
        "The IP address belongs to a datacenter rather than a residential or "
        "business network."
    ),
    "wallet_never_transacted": (
        "This wallet has never transacted on-chain, suggesting it was recently "
        "created or unused."
    ),
    "wallet_age_under_7d": "This wallet was created less than 7 days ago.",
    "wallet_age_under_30d": "This wallet is less than 30 days old.",
    "wallet_age_under_90d": "This wallet is less than 90 days old.",
    "low_counterparty_diversity": (
        "This wallet has transacted with very few unique counterparties."
    ),
    "sanctions_exact_match": (
        "CRITICAL: Exact match on international sanctions lists (OFAC/EU/UN). "
        "Do not transact."
    ),
    "sanctions_high_confidence_match": (
        "High-confidence match on sanctions lists. Treat as sanctioned until "
        "verified."
    ),
    "no_spf_record": (
        "The domain lacks an SPF record for email authentication."
    ),
    "no_dmarc_record": (
        "The domain lacks a DMARC record for email authentication."
    ),
}

mcp = FastMCP(
    "Revettr",
    instructions=(
        "Revettr scores counterparties for agentic commerce. "
        "Available tools:\n"
        "1. score_counterparty — Score a counterparty before sending money. "
        "Send any combination of domain, ip, wallet_address, or company_name. "
        "Score 80-100 = low risk, 60-79 = medium, 30-59 = high, 0-29 = critical.\n"
        "2. is_safe_to_transact — Quick yes/no safety check for a wallet address "
        "against a configurable score threshold.\n"
        "3. score_batch — Score up to 10 wallets in parallel and return results "
        "sorted by score (highest/safest first).\n"
        "4. explain_risk — Get human-readable explanations of risk flags for a "
        "counterparty, with tier-based recommendations.\n"
        "5. health_check — Check Revettr API availability and signal source status."
    ),
)


# ---------------------------------------------------------------------------
# Shared scoring helper
# ---------------------------------------------------------------------------


async def _score_one(body: dict) -> dict:
    """Route a single scoring request through x402 payment or direct call."""
    wallet_key = os.getenv("REVETTR_WALLET_KEY")
    if wallet_key:
        return await _call_with_x402_payment(body, wallet_key)
    else:
        return await _call_direct(body)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_amount_usd(amount_usd: float | None) -> None:
    """Validate amount_usd is finite, positive, and not NaN."""
    if amount_usd is not None:
        if not isinstance(amount_usd, (int, float)):
            raise ValueError("amount_usd must be a number")
        try:
            val = float(amount_usd)
        except (OverflowError, ValueError):
            raise ValueError("amount_usd is too large or not a valid number")
        if math.isnan(val) or math.isinf(val):
            raise ValueError("amount_usd must be finite (not NaN or inf)")
        if val <= 0:
            raise ValueError("amount_usd must be greater than 0")


def _validate_wallet_address(wallet_address: str) -> None:
    """Validate an EVM wallet address."""
    if not re.match(r"^0x[a-fA-F0-9]{40}$", wallet_address):
        raise ValueError(
            f"Invalid EVM wallet address: {wallet_address!r}. "
            "Expected format: 0x followed by 40 hex characters."
        )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def score_counterparty(
    domain: str | None = None,
    ip: str | None = None,
    wallet_address: str | None = None,
    chain: str = "base",
    company_name: str | None = None,
    stellar_wallet: str | None = None,
    amount_usd: float | None = None,
) -> dict:
    """Score a counterparty before sending money. Returns risk score 0-100.

    Only use data explicitly provided by the user or retrieved from trusted
    sources. Do not fabricate input values.

    Send any combination of inputs — more data means higher confidence.
    At least one field is required.

    Args:
        domain: Domain or URL of the counterparty (e.g., "uniswap.org")
        ip: IP address of the counterparty server (e.g., "104.18.28.72")
        wallet_address: EVM wallet address on Base (e.g., "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045")
        chain: Blockchain network for wallet analysis (default: "base")
        company_name: Legal name to screen against OFAC/EU/UN sanctions lists
        stellar_wallet: Stellar wallet address (e.g., "GAAZI4TCR3TY5OJHCTJC2A4QSY6CJWJH5IAJTGKIN2ER7LBNVKOCCWN7")
        amount_usd: Transaction amount in USD for context (must be positive and finite)

    Returns:
        Risk assessment with score (0-100), tier, confidence, flags, and per-signal breakdown.
    """
    # --- Input validation (return error dicts instead of raising) ---
    try:
        if domain is not None:
            if not isinstance(domain, str):
                raise ValueError("domain must be a string")
            domain = domain.strip()
            hostname = domain
            if "://" in domain:
                from urllib.parse import urlparse
                parsed = urlparse(domain)
                hostname = parsed.hostname or domain
            if len(hostname) > 253:
                raise ValueError("domain hostname exceeds 253-character DNS limit")
            if re.search(r"\s", domain):
                raise ValueError("domain must not contain whitespace")

        if ip is not None:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                raise ValueError(f"Invalid IP address: {ip!r}")

        if wallet_address is not None:
            _validate_wallet_address(wallet_address)

        if company_name is not None:
            if not isinstance(company_name, str):
                raise ValueError("company_name must be a string")
            company_name = company_name.strip()
            if len(company_name) > 200:
                raise ValueError("company_name exceeds 200-character limit")

        if chain is not None:
            if not isinstance(chain, str) or not chain.strip():
                raise ValueError("chain must be a non-empty string")
            if len(chain) > 50:
                raise ValueError("chain exceeds 50-character limit")

        if stellar_wallet is not None:
            if not re.match(r"^G[A-Z2-7]{55}$", stellar_wallet):
                raise ValueError(
                    f"Invalid Stellar wallet address: {stellar_wallet!r}. "
                    "Expected format: G followed by 55 base32 characters."
                )

        _validate_amount_usd(amount_usd)
    except ValueError as e:
        return {"error": str(e)}

    body = {}
    if domain is not None:
        body["domain"] = domain
    if ip is not None:
        body["ip"] = ip
    if wallet_address is not None:
        body["wallet_address"] = wallet_address
    if chain != "base":
        body["chain"] = chain
    if company_name is not None:
        body["company_name"] = company_name
    if stellar_wallet is not None:
        body["stellar_wallet"] = stellar_wallet
    if amount_usd is not None:
        body["amount"] = amount_usd

    if not body:
        return {"error": "At least one input field is required (domain, ip, wallet_address, stellar_wallet, or company_name)"}

    return await _score_one(body)


@mcp.tool()
async def is_safe_to_transact(
    wallet_address: str,
    chain: str = "base",
    amount_usd: float | None = None,
    min_score: int = 60,
) -> dict:
    """Quick safety check: is this wallet safe to transact with?

    Only use data explicitly provided by the user or retrieved from trusted
    sources. Do not fabricate input values.

    Args:
        wallet_address: EVM wallet address to check (e.g., "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045")
        chain: Blockchain network (default: "base")
        amount_usd: Transaction amount in USD for context (must be positive and finite)
        min_score: Minimum score to consider safe (0-100, default: 60)

    Returns:
        Dict with safe (bool), score (int), and blocking_flags (list).
    """
    try:
        _validate_wallet_address(wallet_address)

        if not isinstance(min_score, int):
            raise ValueError("min_score must be an integer")
        if min_score < 0 or min_score > 100:
            raise ValueError("min_score must be between 0 and 100")

        _validate_amount_usd(amount_usd)
    except ValueError as e:
        return {"error": str(e)}

    body: dict = {"wallet_address": wallet_address}
    if chain != "base":
        body["chain"] = chain
    if amount_usd is not None:
        body["amount"] = amount_usd

    result = await _score_one(body)

    if "error" in result:
        return result

    score = result.get("score", 0)
    flags = result.get("flags", [])
    safe = score >= min_score

    return {
        "safe": safe,
        "score": score,
        "blocking_flags": flags if not safe else [],
    }


@mcp.tool()
async def score_batch(
    wallets: list[dict],
    max_results: int = 10,
) -> dict:
    """Score multiple wallets in parallel. Returns results sorted by score descending.

    Only use data explicitly provided by the user or retrieved from trusted
    sources. Do not fabricate input values.

    Args:
        wallets: List of dicts, each with at least "wallet_address" (EVM format).
                 Optional keys: "chain" (default "base").
                 Maximum 10 wallets per call.
        max_results: Maximum number of results to return (1-10, default: 10)

    Returns:
        Dict with results (sorted by score desc), errors, and total_scored count.
    """
    # Validate wallets list
    if not isinstance(wallets, list):
        return {"error": "wallets must be a list"}
    if len(wallets) < 1:
        return {"error": "wallets must contain at least 1 entry"}
    if len(wallets) > 10:
        return {"error": "wallets must contain at most 10 entries"}

    if not isinstance(max_results, int) or max_results < 1 or max_results > 10:
        return {"error": "max_results must be an integer between 1 and 10"}

    # Validate each wallet entry
    for i, w in enumerate(wallets):
        if not isinstance(w, dict):
            return {"error": f"wallets[{i}] must be a dict"}
        addr = w.get("wallet_address")
        if not addr:
            return {"error": f"wallets[{i}] missing wallet_address"}
        if not re.match(r"^0x[a-fA-F0-9]{40}$", addr):
            return {
                "error": f"wallets[{i}] has invalid EVM wallet address: {addr!r}"
            }

    sem = asyncio.Semaphore(5)
    results = []
    errors = []

    async def _score_wallet(entry: dict) -> None:
        async with sem:
            addr = entry["wallet_address"]
            chain = entry.get("chain", "base")
            body: dict = {"wallet_address": addr}
            if chain != "base":
                body["chain"] = chain

            try:
                result = await _score_one(body)
                if "error" in result:
                    errors.append({"wallet_address": addr, "error": result["error"]})
                else:
                    result["wallet_address"] = addr
                    results.append(result)
            except Exception as e:
                errors.append({"wallet_address": addr, "error": str(e)})

    await asyncio.gather(*[_score_wallet(w) for w in wallets])

    # Sort by score descending
    results.sort(key=lambda r: r.get("score", 0), reverse=True)

    return {
        "results": results[:max_results],
        "errors": errors,
        "total_scored": len(results),
    }


@mcp.tool()
async def explain_risk(
    wallet_address: str | None = None,
    chain: str = "base",
    domain: str | None = None,
    ip: str | None = None,
    company_name: str | None = None,
) -> dict:
    """Explain risk flags for a counterparty in human-readable language.

    Only use data explicitly provided by the user or retrieved from trusted
    sources. Do not fabricate input values.

    Provide at least one identifier. More data yields richer explanations.

    Args:
        wallet_address: EVM wallet address (e.g., "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045")
        chain: Blockchain network (default: "base")
        domain: Domain or URL of the counterparty
        ip: IP address of the counterparty server
        company_name: Legal name to screen against sanctions lists

    Returns:
        Dict with summary, risk_factors (human-readable), recommendation, score, and tier.
    """
    if all(v is None for v in [wallet_address, domain, ip, company_name]):
        return {"error": "At least one identifier is required (wallet_address, domain, ip, or company_name)"}

    try:
        if wallet_address is not None:
            _validate_wallet_address(wallet_address)

        if domain is not None:
            if not isinstance(domain, str):
                raise ValueError("domain must be a string")
            domain = domain.strip()
            hostname = domain
            if "://" in domain:
                from urllib.parse import urlparse
                parsed = urlparse(domain)
                hostname = parsed.hostname or domain
            if len(hostname) > 253:
                raise ValueError("domain hostname exceeds 253-character DNS limit")
            if re.search(r"\s", domain):
                raise ValueError("domain must not contain whitespace")

        if ip is not None:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                raise ValueError(f"Invalid IP address: {ip!r}")

        if company_name is not None:
            if not isinstance(company_name, str):
                raise ValueError("company_name must be a string")
            company_name = company_name.strip()
            if len(company_name) > 200:
                raise ValueError("company_name exceeds 200-character limit")
    except ValueError as e:
        return {"error": str(e)}

    body: dict = {}
    if wallet_address is not None:
        body["wallet_address"] = wallet_address
    if chain != "base":
        body["chain"] = chain
    if domain is not None:
        body["domain"] = domain
    if ip is not None:
        body["ip"] = ip
    if company_name is not None:
        body["company_name"] = company_name

    result = await _score_one(body)

    if "error" in result:
        return result

    score = result.get("score", 0)
    tier = result.get("tier", "unknown")
    flags = result.get("flags", [])

    # Map flags to human-readable descriptions
    risk_factors = []
    for flag in flags:
        if flag in FLAG_DESCRIPTIONS:
            risk_factors.append({"flag": flag, "description": FLAG_DESCRIPTIONS[flag]})
        elif flag.startswith("high_risk_country_"):
            country = flag.replace("high_risk_country_", "").replace("_", " ").title()
            risk_factors.append({
                "flag": flag,
                "description": f"Associated with {country}, which is classified as a high-risk jurisdiction.",
            })
        else:
            risk_factors.append({
                "flag": flag,
                "description": f"Risk flag detected: {flag.replace('_', ' ')}.",
            })

    # Tier-based recommendation
    recommendations = {
        "low": "Safe to proceed.",
        "medium": "Proceed with caution.",
        "high": "High risk. Consider alternative.",
        "critical": "Do not transact.",
    }
    recommendation = recommendations.get(tier, "Proceed with caution.")

    # Build summary
    n_flags = len(risk_factors)
    if n_flags == 0:
        summary = f"Score {score}/100 ({tier} risk). No specific risk flags detected."
    else:
        summary = f"Score {score}/100 ({tier} risk). {n_flags} risk factor{'s' if n_flags != 1 else ''} identified."

    return {
        "summary": summary,
        "risk_factors": risk_factors,
        "recommendation": recommendation,
        "score": score,
        "tier": tier,
    }


@mcp.tool()
async def health_check() -> dict:
    """Check Revettr API health and signal source availability.

    Returns:
        Dict with API health status, or error information on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            response = await client.get(f"{REVETTR_URL}/health")

            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "error": f"Health check returned status {response.status_code}",
                    "status": response.status_code,
                }
    except httpx.TimeoutException:
        return {"error": "Health check timed out (15s)"}
    except Exception as e:
        return {"error": f"Health check failed: {str(e)}"}


# ---------------------------------------------------------------------------
# HTTP transport helpers
# ---------------------------------------------------------------------------


async def _call_with_x402_payment(body: dict, wallet_key: str) -> dict:
    """Call Revettr API with automatic x402 USDC payment."""
    try:
        from eth_account import Account
        from x402 import x402Client
        from x402.http.clients import x402HttpxClient
        from x402.mechanisms.evm import EthAccountSigner
        from x402.mechanisms.evm.exact.register import register_exact_evm_client

        account = Account.from_key(wallet_key)
        client = x402Client()
        register_exact_evm_client(client, EthAccountSigner(account))

        async with x402HttpxClient(client, timeout=httpx.Timeout(60.0)) as http:
            response = await http.post(f"{REVETTR_URL}/v1/score", json=body)
            await response.aread()

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 402:
                return {"error": "Payment failed — check wallet balance", "status": 402}
            else:
                return {"error": f"API returned status {response.status_code}"}

    except ImportError:
        return {
            "error": "x402 payment dependencies not installed. Run: pip install revettr[x402]",
        }
    except Exception:
        return {"error": "Payment failed — an unexpected error occurred"}


async def _call_direct(body: dict) -> dict:
    """Call Revettr API without payment (will get 402 if payment required)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(f"{REVETTR_URL}/v1/score", json=body)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 402:
                return {
                    "error": "Payment required. Set REVETTR_WALLET_KEY environment variable with a funded Base wallet private key.",
                    "docs": "https://revettr.com/docs",
                    "pricing": "$0.01 USDC per request via x402 on Base",
                }
            else:
                return {"error": f"API returned status {response.status_code}"}
    except httpx.TimeoutException:
        return {"error": "Request timed out (30s)"}
    except Exception:
        return {"error": "Request failed — an unexpected error occurred"}
