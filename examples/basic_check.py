"""Basic counterparty risk check — no payment (will get 402 on live API)."""

from revettr import Revettr

# Point to local dev server (no payment required when x402 middleware is disabled)
client = Revettr(base_url="http://localhost:4021")

# Score with domain + IP
score = client.score(
    domain="uniswap.org",
    ip="104.18.28.72",
)

print(f"Score: {score.score}/100 ({score.tier})")
print(f"Confidence: {score.confidence}")
print(f"Signals checked: {score.signals_checked}")
print(f"Flags: {score.flags}")

# Check individual signals
for name, signal in score.signal_scores.items():
    print(f"  {name}: {signal.score}/100 — flags: {signal.flags}")
