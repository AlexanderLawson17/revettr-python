"""Revettr Python client — counterparty risk scoring for agentic commerce."""

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
        self.timeout = timeout
        self._wallet_private_key = wallet_private_key
        self._http_client: httpx.Client | None = None
        self._x402_client = None

        if wallet_private_key:
            self._setup_x402()

    def _setup_x402(self):
        """Set up x402 auto-payment client."""
        try:
            from eth_account import Account
            from x402 import x402Client
            from x402.http.clients import x402HttpxClient
            from x402.mechanisms.evm import EthAccountSigner
            from x402.mechanisms.evm.exact.register import register_exact_evm_client

            account = Account.from_key(self._wallet_private_key)
            client = x402Client()
            register_exact_evm_client(client, EthAccountSigner(account))
            self._x402_client = client
        except ImportError:
            raise ImportError(
                "x402 auto-payment requires additional dependencies. "
                "Install with: pip install revettr[x402]"
            )

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
        """
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
