"""Revettr MCP Server — counterparty risk scoring as an MCP tool.

Wraps the Revettr REST API (revettr.com) so MCP clients like
Claude Desktop, Cursor, and Windsurf can call score_counterparty
as a native tool.
"""

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
    is_local = hostname in ("localhost", "127.0.0.1") or hostname.startswith("127.")
    if not is_local and not url.startswith("https://"):
        raise ValueError(
            f"REVETTR_URL must use HTTPS (got {url!r}). "
            "HTTP is only allowed for localhost/127.0.0.1 during development."
        )


_validate_url(REVETTR_URL)

mcp = FastMCP(
    "Revettr",
    instructions=(
        "Revettr scores counterparties for agentic commerce. "
        "Use score_counterparty before sending money to an unknown entity. "
        "Send any combination of domain, ip, wallet_address, or company_name. "
        "Score 80-100 = low risk, 60-79 = medium, 30-59 = high, 0-29 = critical."
    ),
)


@mcp.tool()
async def score_counterparty(
    domain: str | None = None,
    ip: str | None = None,
    wallet_address: str | None = None,
    chain: str = "base",
    company_name: str | None = None,
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
            if not re.match(r"^0x[a-fA-F0-9]{40}$", wallet_address):
                raise ValueError(
                    f"Invalid EVM wallet address: {wallet_address!r}. "
                    "Expected format: 0x followed by 40 hex characters."
                )

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

    if not body:
        return {"error": "At least one input field is required (domain, ip, wallet_address, or company_name)"}

    wallet_key = os.getenv("REVETTR_WALLET_KEY")

    if wallet_key:
        return await _call_with_x402_payment(body, wallet_key)
    else:
        return await _call_direct(body)


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
