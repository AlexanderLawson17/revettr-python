"""Full counterparty check — all available signals."""

from revettr import Revettr

client = Revettr(base_url="http://localhost:4021")

score = client.score(
    domain="merchant-service.com",
    ip="185.220.101.42",
    wallet_address="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
    company_name="Merchant Service LLC",
)

print(f"Composite Score: {score.score}/100")
print(f"Tier: {score.tier}")
print(f"Confidence: {score.confidence:.0%}")
print(f"Signals: {score.signals_checked}")
print()

# Decision logic
if score.score >= 80:
    print("PROCEED — low risk counterparty")
elif score.score >= 60:
    print("CAUTION — review flags before transacting")
    for flag in score.flags:
        print(f"  - {flag}")
elif score.score >= 30:
    print("HIGH RISK — consider alternative counterparty")
    for flag in score.flags:
        print(f"  - {flag}")
else:
    print("DO NOT TRANSACT — critical risk")
    for flag in score.flags:
        print(f"  ! {flag}")

print()
print("Signal breakdown:")
for name, signal in score.signal_scores.items():
    status = "available" if signal.available else "UNAVAILABLE"
    print(f"  {name}: {signal.score}/100 ({status})")
    if signal.flags:
        for flag in signal.flags:
            print(f"    - {flag}")
