"""Minimal wallet-only check — the most common use case for x402 agents."""

from revettr import Revettr

client = Revettr(base_url="http://localhost:4021")

# Just a wallet address — the API checks on-chain history
score = client.score(
    wallet_address="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
)

print(f"Score: {score.score}/100 ({score.tier})")

if score.tier in ("high", "critical"):
    print("WARNING: High risk counterparty")
    for flag in score.flags:
        print(f"  - {flag}")
else:
    print("Counterparty appears legitimate")
