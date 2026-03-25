"""Example: Safe x402 payment with automatic counterparty risk check.

The SafeX402Client wraps x402 payments with Revettr risk scoring.
Before sending any payment, it automatically checks the counterparty
and blocks payments to risky services.

Usage:
    pip install revettr[x402]
    export WALLET_PRIVATE_KEY="0x..."
    python examples/safe_payment.py
"""

import asyncio
import os

from revettr import SafeX402Client, PaymentBlocked


async def main():
    wallet_key = os.environ["WALLET_PRIVATE_KEY"]

    # Safe client blocks payments to counterparties scoring below 60/100
    async with SafeX402Client(
        wallet_private_key=wallet_key,
        min_score=60,       # Block "high" and "critical" risk tiers
        on_fail="block",    # Raise PaymentBlocked (default)
    ) as http:
        try:
            # This request automatically:
            # 1. Checks the domain via Revettr (pays $0.01 USDC)
            # 2. If score >= 60, proceeds with the x402 payment
            # 3. If score < 60, raises PaymentBlocked
            response = await http.post(
                "https://some-x402-api.com/endpoint",
                json={"query": "example"},
            )
            print(f"Response: {response.json()}")

        except PaymentBlocked as e:
            print(f"Blocked: {e}")
            print(f"  Score: {e.score}/100")
            print(f"  Tier: {e.tier}")
            print(f"  Flags: {e.flags}")


if __name__ == "__main__":
    asyncio.run(main())
