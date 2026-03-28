"""Safe x402 payment client — auto-checks counterparty risk before paying."""

import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("revettr.safe_x402")


class PaymentBlocked(Exception):
    """Raised when a payment is blocked due to counterparty risk score."""

    def __init__(self, url: str, score: int, tier: str, flags: list[str]):
        self.url = url
        self.score = score
        self.tier = tier
        self.flags = flags
        super().__init__(
            f"Payment blocked: {url} scored {score}/100 (tier={tier}). "
            f"Flags: {', '.join(flags) if flags else 'none'}"
        )


class RevettrCheckError(Exception):
    """Raised when fail_closed=True and the Revettr risk check cannot be completed."""

    def __init__(self, domain: str, reason: str):
        self.domain = domain
        self.reason = reason
        super().__init__(
            f"Revettr check failed for {domain} (fail_closed=True): {reason}"
        )


class SafeX402Client:
    """Drop-in x402 payment client that checks counterparty risk before paying.

    Wraps x402HttpxClient to automatically score the target domain via Revettr
    before any x402 payment is sent. If the counterparty scores below the
    threshold, the payment is blocked.

    Usage:
        from revettr.safe_x402 import SafeX402Client

        async with SafeX402Client(wallet_private_key="0x...") as http:
            # Automatically checks revettr.com before paying
            response = await http.post("https://some-api.com/endpoint", json=data)

    Args:
        wallet_private_key: EVM private key for x402 payments
        min_score: Minimum risk score to allow payment (default: 60, "medium" tier)
        on_fail: What to do when score is below threshold:
            - "block" (default): Raise PaymentBlocked exception
            - "warn": Log warning but proceed with payment
            - "log": Silently log and proceed
        revettr_url: Revettr API URL (default: https://revettr.com)
        timeout: HTTP timeout in seconds (default: 60.0)
        fail_closed: If True, raise RevettrCheckError when the Revettr API is
            unreachable or returns a non-200 status, instead of silently
            proceeding with payment. Default is False for backwards
            compatibility. Security-conscious deployments should set this to
            True to prevent payments when risk cannot be assessed.
    """

    def __init__(
        self,
        wallet_private_key: str,
        *,
        min_score: int = 60,
        on_fail: str = "block",
        revettr_url: str = "https://revettr.com",
        timeout: float = 60.0,
        fail_closed: bool = False,
    ):
        if on_fail not in ("block", "warn", "log"):
            raise ValueError(f"on_fail must be 'block', 'warn', or 'log', got {on_fail!r}")
        if not 0 <= min_score <= 100:
            raise ValueError(f"min_score must be 0-100, got {min_score}")

        self._min_score = min_score
        self._on_fail = on_fail
        self._revettr_url = revettr_url.rstrip("/")
        self._timeout = timeout
        self._fail_closed = fail_closed
        self._checked_domains: dict[str, int] = {}  # Cache: domain -> score

        # Set up x402 client
        try:
            from eth_account import Account
            from x402 import x402Client
            from x402.mechanisms.evm import EthAccountSigner
            from x402.mechanisms.evm.exact.register import register_exact_evm_client

            account = Account.from_key(wallet_private_key)
            self._x402_client = x402Client()
            register_exact_evm_client(self._x402_client, EthAccountSigner(account))
        except ImportError:
            raise ImportError(
                "Safe x402 client requires x402 dependencies. "
                "Install with: pip install revettr[x402]"
            )

        self._http_client = None

    async def __aenter__(self):
        from x402.http.clients import x402HttpxClient
        self._http_client = x402HttpxClient(
            self._x402_client,
            timeout=httpx.Timeout(self._timeout),
        )
        await self._http_client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._http_client:
            await self._http_client.__aexit__(exc_type, exc_val, exc_tb)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        """POST with automatic counterparty risk check before x402 payment."""
        await self._check_counterparty(url)
        response = await self._http_client.post(url, **kwargs)
        await response.aread()
        return response

    async def get(self, url: str, **kwargs) -> httpx.Response:
        """GET with automatic counterparty risk check before x402 payment."""
        await self._check_counterparty(url)
        response = await self._http_client.get(url, **kwargs)
        await response.aread()
        return response

    def _cache_domain(self, domain: str, score: int) -> None:
        """Cache a domain score, evicting the oldest entry if at capacity."""
        if len(self._checked_domains) >= 1000:
            # Remove oldest entry (first inserted key in insertion-ordered dict)
            oldest = next(iter(self._checked_domains))
            del self._checked_domains[oldest]
        self._checked_domains[domain] = score

    async def _check_counterparty(self, url: str) -> None:
        """Score the target domain before allowing payment."""
        domain = urlparse(url).hostname
        if not domain:
            return

        # Skip if already checked this domain in this session
        if domain in self._checked_domains:
            cached_score = self._checked_domains[domain]
            if cached_score >= self._min_score:
                return
            # Re-check on cached failures (score may have changed)

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                resp = await client.post(
                    f"{self._revettr_url}/v1/score",
                    json={"domain": domain},
                )

                if resp.status_code == 402:
                    # Revettr itself requires payment — use x402 client for the check
                    resp = await self._http_client.post(
                        f"{self._revettr_url}/v1/score",
                        json={"domain": domain},
                    )
                    await resp.aread()

                if resp.status_code != 200:
                    if self._fail_closed:
                        raise RevettrCheckError(domain, f"API returned status {resp.status_code}")
                    logger.warning("Revettr check failed (status %d) for %s — proceeding", resp.status_code, domain)
                    return

                data = resp.json()
                score = data.get("score", 0)
                tier = data.get("tier", "unknown")
                flags = data.get("flags", [])

        except RevettrCheckError:
            raise
        except Exception as e:
            if self._fail_closed:
                raise RevettrCheckError(domain, str(e)) from e
            logger.warning("Revettr check failed for %s: %s — proceeding", domain, e)
            return

        # Cache the result (bounded)
        self._cache_domain(domain, score)

        if score >= self._min_score:
            logger.info("Counterparty check passed: %s scored %d/100 (%s)", domain, score, tier)
            return

        # Score below threshold
        msg = f"Counterparty risk check: {domain} scored {score}/100 (tier={tier}, flags={flags})"

        if self._on_fail == "block":
            raise PaymentBlocked(url, score, tier, flags)
        elif self._on_fail == "warn":
            logger.warning("PAYMENT PROCEEDING DESPITE LOW SCORE — %s", msg)
        else:  # "log"
            logger.info(msg)
