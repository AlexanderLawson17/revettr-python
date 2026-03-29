"""Revettr Python client — counterparty risk scoring for agentic commerce."""

import ipaddress
import math
import re

import httpx

from revettr.models import ScoreResponse


class Revettr:
    """Client for the Revettr counterparty risk scoring API.

    Basic usage (returns 402 without x402 payment setup):
        client = Revettr()
        score = client.score(domain="example.com")

    With x402 auto-payment:
        client = Revettr(wallet_private_key="0x...")
        score = client.score(domain="example.com")  # Pays automatically
    """

    DEFAULT_URL = "https://revettr.com"

    def __init__(
        self,
        base_url: str | None = None,
        wallet_private_key: str | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = (base_url or self.DEFAULT_URL).rstrip("/")
        self._validate_base_url(self.base_url)
        self.timeout = timeout
        self._http_client: httpx.Client | None = None
        self._x402_client = None

        if wallet_private_key:
            self._setup_x402(wallet_private_key)

    def __repr__(self) -> str:
        return (
            f"Revettr(base_url={self.base_url!r}, "
            f"x402={'enabled' if self._x402_client else 'disabled'})"
        )

    @staticmethod
    def _validate_base_url(url: str) -> None:
        """Ensure base_url uses HTTPS (allow HTTP only for localhost)."""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        try:
            is_local = hostname in ("localhost",) or ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_local = False
        if not is_local and not url.startswith("https://"):
            raise ValueError(
                f"base_url must use HTTPS (got {url!r}). "
                "HTTP is only allowed for localhost/127.0.0.1 during development."
            )

    def _setup_x402(self, wallet_private_key: str):
        """Set up x402 auto-payment client. Does not store the raw key."""
        try:
            from eth_account import Account
            from x402 import x402Client
            from x402.http.clients import x402HttpxClient
            from x402.mechanisms.evm import EthAccountSigner
            from x402.mechanisms.evm.exact.register import register_exact_evm_client

            account = Account.from_key(wallet_private_key)
            client = x402Client()
            register_exact_evm_client(client, EthAccountSigner(account))
            self._x402_client = client
        except ImportError:
            raise ImportError(
                "x402 auto-payment requires additional dependencies. "
                "Install with: pip install revettr[x402]"
            )

    @staticmethod
    def _validate_inputs(
        domain: str | None,
        ip: str | None,
        wallet_address: str | None,
        chain: str,
        company_name: str | None,
        email: str | None,
        amount: float | None,
    ) -> None:
        """Validate inputs before sending to the API (defense-in-depth)."""
        if domain is not None:
            if not isinstance(domain, str):
                raise ValueError("domain must be a string")
            domain = domain.strip()
            # Extract hostname if input is a URL, then apply DNS limit
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
            if len(company_name.strip()) > 200:
                raise ValueError("company_name exceeds 200-character limit")

        if amount is not None:
            if not isinstance(amount, (int, float)):
                raise ValueError("amount must be a number")
            try:
                amount_f = float(amount)
            except (OverflowError, ValueError):
                raise ValueError("amount is too large or not a valid number")
            if math.isnan(amount_f) or math.isinf(amount_f):
                raise ValueError("amount must be finite (not NaN or inf)")
            if amount_f <= 0:
                raise ValueError("amount must be greater than 0")

        if email is not None:
            if not isinstance(email, str):
                raise ValueError("email must be a string")
            if len(email) > 254:
                raise ValueError("email exceeds 254-character limit")
            at_pos = email.find("@")
            if at_pos == -1 or "." not in email[at_pos + 1 :]:
                raise ValueError(f"Invalid email address: {email!r}")

        if chain is not None:
            if not isinstance(chain, str) or not chain.strip():
                raise ValueError("chain must be a non-empty string")
            if len(chain) > 50:
                raise ValueError("chain exceeds 50-character limit")

    def score(
        self,
        domain: str | None = None,
        ip: str | None = None,
        wallet_address: str | None = None,
        chain: str = "base",
        company_name: str | None = None,
        email: str | None = None,
        amount: float | None = None,
    ) -> ScoreResponse:
        """Score a counterparty. Send whatever data you have.

        Args:
            domain: Domain or URL of the counterparty
            ip: IP address of the counterparty server
            wallet_address: EVM wallet address (0x...)
            chain: Blockchain network (default: "base")
            company_name: Name to screen against sanctions lists
            email: Email address (future signal, not yet scored)
            amount: Transaction amount in USD (context only)

        Returns:
            ScoreResponse with composite score, tier, flags, and per-signal breakdown

        Raises:
            RevettrPaymentRequired: If no x402 wallet is configured and payment is needed
            RevettrError: If the API returns an error
            ValueError: If any input fails validation
        """
        self._validate_inputs(domain, ip, wallet_address, chain, company_name, email, amount)

        # Strip whitespace from string inputs after validation
        if domain is not None:
            domain = domain.strip()
        if company_name is not None:
            company_name = company_name.strip()

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
        if email is not None:
            body["email"] = email
        if amount is not None:
            body["amount"] = amount

        if not body:
            raise ValueError("At least one input field is required")

        if self._x402_client:
            return self._score_with_payment(body)
        return self._score_direct(body)

    def _score_direct(self, body: dict) -> ScoreResponse:
        """Make a direct HTTP request (no x402 payment)."""
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(f"{self.base_url}/v1/score", json=body)

            if resp.status_code == 402:
                raise RevettrPaymentRequired(
                    "Payment required. Either provide a wallet_private_key to "
                    "Revettr() for auto-payment, or handle the x402 flow manually."
                )

            resp.raise_for_status()
            return ScoreResponse.from_dict(resp.json())

    def _score_with_payment(self, body: dict) -> ScoreResponse:
        """Make a request with x402 auto-payment."""
        import asyncio
        from x402.http.clients import x402HttpxClient

        async def _call():
            async with x402HttpxClient(self._x402_client) as http:
                response = await http.post(
                    f"{self.base_url}/v1/score",
                    json=body,
                )
                await response.aread()
                if response.status_code == 402:
                    raise RevettrPaymentRequired("Payment failed — check wallet balance")
                return ScoreResponse.from_dict(response.json())

        return asyncio.run(_call())

    def health(self) -> dict:
        """Check API health and signal source availability."""
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(f"{self.base_url}/health")
            resp.raise_for_status()
            return resp.json()


class RevettrError(Exception):
    """Base exception for Revettr client errors."""
    pass


class RevettrPaymentRequired(RevettrError):
    """Raised when x402 payment is required but not configured."""
    pass
