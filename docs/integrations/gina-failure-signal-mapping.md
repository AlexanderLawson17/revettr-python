# Ask Gina x Revettr: Failure Signal Mapping

**Version**: 1.0
**Date**: 2026-04-02
**Status**: Draft
**Partners**: Ask Gina (DeFi Execution Agent), Revettr (Counterparty Risk Scoring)

## Overview

Ask Gina is a DeFi execution agent with $5M+ in transaction volume, 100K+
transactions, and 18 months of production data. During that time, Gina has
accumulated a rich dataset of transaction failures -- gas drains, MEV attacks,
bridge locks, and slippage events -- each labeled with root cause and financial
impact.

Revettr currently scores counterparties using domain intelligence, IP reputation,
on-chain wallet history, and sanctions screening. These signals are strong for
identifying bad actors but do not capture DeFi-specific execution risks like MEV
exposure or bridge reliability.

This document maps Gina's failure modes to new Revettr scoring signals. The
partnership creates a feedback loop: Gina provides labeled failure data, Revettr
converts it into predictive signals, and both systems get smarter. Gina's agents
get pre-execution risk checks; Revettr gets the highest-quality DeFi failure
dataset in the market.

## Failure Mode to Signal Mapping

| Failure Mode | Revettr Signal | Score Impact | Description |
|-------------|----------------|-------------|-------------|
| Gas drain | `contract_high_revert_rate` | -15 to -30 | Contract consumes gas but reverts. Gina sees this as failed txns where gas was spent but no state change occurred. A revert rate >20% on a contract is a strong negative signal. |
| MEV front-running | `mev_exposure` | -10 to -25 | Transaction was sandwiched or front-run by MEV bots. Gina detects this by comparing expected vs actual execution price. Pools or routers with high MEV incidence get flagged. |
| Bridge locks | `bridge_lock_incidents` | -20 to -40 | Funds locked in a bridge for >24h or permanently lost. Gina tracks bridge completion times; bridges with >2% lock rate are high risk. This is the most financially damaging failure mode. |
| Slippage | `low_liquidity_pool` | -5 to -20 | Execution price deviated >2% from quote due to thin liquidity. Gina measures slippage across pools; consistently high slippage indicates a pool that agents should avoid or size down. |

### Impact Scaling

Score impact scales with severity within each range:

- **Gas drain**: -15 for revert rate 20-35%, -22 for 35-50%, -30 for >50%
- **MEV exposure**: -10 for <5% of txns affected, -18 for 5-15%, -25 for >15%
- **Bridge locks**: -20 for lock rate 2-5%, -30 for 5-10%, -40 for >10%
- **Slippage**: -5 for avg slippage 2-5%, -12 for 5-10%, -20 for >10%

## Proposed SignalScore Definitions

Following Revettr's existing `SignalScore` dataclass shape:

```python
from dataclasses import dataclass, field


@dataclass
class SignalScore:
    """Score from a single signal group."""
    score: int
    flags: list[str] = field(default_factory=list)
    available: bool = True
    details: dict = field(default_factory=dict)
```

### Gas Drain Signal

```python
SignalScore(
    score=55,
    flags=["contract_high_revert_rate"],
    available=True,
    details={
        "contract_address": "0xdead...",
        "revert_rate": 0.38,
        "sample_size": 1200,
        "observation_period_days": 90,
        "source": "gina_failure_data",
    },
)
```

### MEV Exposure Signal

```python
SignalScore(
    score=68,
    flags=["mev_exposure"],
    available=True,
    details={
        "pool_address": "0xbeef...",
        "mev_incident_rate": 0.08,
        "avg_extraction_bps": 45,
        "sample_size": 3400,
        "observation_period_days": 90,
        "source": "gina_failure_data",
    },
)
```

### Bridge Lock Signal

```python
SignalScore(
    score=30,
    flags=["bridge_lock_incidents"],
    available=True,
    details={
        "bridge_contract": "0xcafe...",
        "lock_rate": 0.07,
        "avg_lock_duration_hours": 72,
        "funds_at_risk_usdc": 12500,
        "sample_size": 800,
        "observation_period_days": 180,
        "source": "gina_failure_data",
    },
)
```

### Low Liquidity Signal

```python
SignalScore(
    score=78,
    flags=["low_liquidity_pool"],
    available=True,
    details={
        "pool_address": "0xfeed...",
        "avg_slippage_bps": 320,
        "median_slippage_bps": 180,
        "liquidity_usd": 45000,
        "sample_size": 5600,
        "observation_period_days": 90,
        "source": "gina_failure_data",
    },
)
```

## Data Partnership

### What Gina Provides

| Data | Format | Frequency | Volume |
|------|--------|-----------|--------|
| Labeled failure events | JSON via webhook or batch upload | Daily | ~200-500 events/day |
| Transaction outcomes (success/failure) | JSON | Daily | ~2,000-5,000/day |
| Contract revert rates | Aggregated CSV | Weekly | All monitored contracts |
| MEV incident logs | JSON with sandwich tx hashes | Daily | ~50-100/day |
| Bridge completion times | JSON with timestamps | Daily | ~100-300/day |
| Pool slippage measurements | JSON with quote vs execution | Daily | ~1,000-3,000/day |

Data format example (failure event):

```json
{
  "event_id": "gina_fail_20260402_001",
  "timestamp": "2026-04-02T14:23:00Z",
  "failure_type": "gas_drain",
  "chain": "base",
  "contract_address": "0xdead...",
  "wallet_address": "0xabc...",
  "tx_hash": "0x123...",
  "gas_spent_wei": "2100000000000000",
  "expected_outcome": "swap_executed",
  "actual_outcome": "reverted",
  "financial_impact_usdc": 3.50,
  "context": {
    "function_called": "swapExactTokensForTokens",
    "revert_reason": "INSUFFICIENT_OUTPUT_AMOUNT"
  }
}
```

### What Revettr Provides

| Data | Format | Access |
|------|--------|--------|
| Pre-execution risk scores | JSON via API | Real-time |
| DeFi signal scores (new) | JSON, included in score response | Real-time |
| Risk alerts for monitored contracts | Webhook | Near real-time |
| Aggregated risk intelligence | Dashboard access | On-demand |

## Integration Architecture

Revettr integrates between Gina's Filter and Executor stages:

```
+------------------+
|   User Request   |
|  "Swap 1000 USDC |
|   for ETH"       |
+--------+---------+
         |
         v
+------------------+
|   Gina Planner   |
|  Route, estimate |
|  gas, pick pool  |
+--------+---------+
         |
         v
+------------------+
|   Gina Filter    |
|  Basic checks:   |
|  slippage limit, |
|  gas ceiling     |
+--------+---------+
         |
         v
+------------------+     +-------------------+
|  REVETTR CHECK   |---->|   Revettr API     |
|  Score the pool  |     |   POST /v1/score  |
|  contract and    |<----|   + DeFi signals   |
|  counterparty    |     +-------------------+
+--------+---------+
         |
    score >= threshold?
    /            \
   YES            NO
    |              |
    v              v
+----------+  +-----------+
|  Gina    |  |  Blocked  |
| Executor |  |  + reason |
| (send tx)|  |  returned |
+----------+  +-----------+
```

### Integration Point

Gina adds a single check between Filter and Executor:

```python
from revettr import Revettr

client = Revettr()


def get_min_score(trade_size_usdc: float) -> int:
    """Dynamic threshold based on trade size.

    Larger trades require higher trust scores.
    """
    if trade_size_usdc >= 10_000:
        return 80
    elif trade_size_usdc >= 1_000:
        return 60
    elif trade_size_usdc >= 100:
        return 40
    else:
        return 20  # Micro-transactions: minimal gating


async def pre_execution_check(
    contract_address: str,
    counterparty_wallet: str,
    counterparty_domain: str | None,
    chain: str,
    trade_size_usdc: float,
) -> dict:
    """Score the counterparty before Gina executes a transaction.

    Returns:
        dict with "approved" (bool), "score", "tier", "flags", and "reason"
    """
    min_score = get_min_score(trade_size_usdc)

    result = client.score(
        wallet_address=counterparty_wallet,
        domain=counterparty_domain,
        chain=chain,
    )

    approved = result.score >= min_score

    response = {
        "approved": approved,
        "score": result.score,
        "tier": result.tier,
        "confidence": result.confidence,
        "flags": result.flags,
        "min_score_required": min_score,
        "trade_size_usdc": trade_size_usdc,
    }

    if not approved:
        response["reason"] = (
            f"Score {result.score}/100 is below the required {min_score} "
            f"for a ${trade_size_usdc:,.2f} trade. "
            f"Tier: {result.tier}. Flags: {', '.join(result.flags) or 'none'}."
        )

    # Check for specific DeFi signals from Gina-sourced data
    defi_warnings = []
    for signal_name, signal_data in result.signal_scores.items():
        for flag in signal_data.flags:
            if flag in (
                "contract_high_revert_rate",
                "mev_exposure",
                "bridge_lock_incidents",
                "low_liquidity_pool",
            ):
                defi_warnings.append(
                    f"{flag} (signal score: {signal_data.score}/100)"
                )

    if defi_warnings:
        response["defi_warnings"] = defi_warnings

    return response


# Example usage in Gina's pipeline
async def gina_execute_swap(plan: dict):
    check = await pre_execution_check(
        contract_address=plan["contract"],
        counterparty_wallet=plan["counterparty_wallet"],
        counterparty_domain=plan.get("counterparty_domain"),
        chain=plan["chain"],
        trade_size_usdc=plan["amount_usdc"],
    )

    if not check["approved"]:
        return {"status": "blocked", "reason": check["reason"]}

    if check.get("defi_warnings"):
        # Log warnings but proceed (operator can configure to block)
        for warning in check["defi_warnings"]:
            print(f"  DeFi warning: {warning}")

    # Proceed to Gina Executor
    # ... execute the transaction ...
    return {"status": "executed", "revettr_score": check["score"]}
```

## Dynamic Threshold by Trade Size

| Trade Size (USDC) | Min Score | Rationale |
|-------------------|-----------|-----------|
| < $100 | 40 | Micro-transactions: low financial risk, allow broader access |
| $100 - $999 | 40 | Small trades: moderate gating, block only high/critical risk |
| $1,000 - $9,999 | 60 | Medium trades: require at least medium tier |
| $10,000+ | 80 | Large trades: require low-risk tier only |

The threshold function is configurable per Gina deployment. Operators managing
institutional funds may set higher minimums across the board.

## Scoring Response with DeFi Signals

Once Gina failure data is integrated, the Revettr score response includes
DeFi-specific signal scores alongside existing signals:

```json
{
  "score": 52,
  "tier": "high",
  "confidence": 0.82,
  "signals_checked": 4,
  "flags": ["contract_high_revert_rate", "mev_exposure"],
  "signal_scores": {
    "domain": {
      "score": 75,
      "flags": [],
      "available": true,
      "details": {"domain_age_days": 400}
    },
    "wallet": {
      "score": 80,
      "flags": [],
      "available": true,
      "details": {"blockchain": {"tx_count": 200, "unique_counterparties": 45}}
    },
    "defi_execution": {
      "score": 42,
      "flags": ["contract_high_revert_rate", "mev_exposure"],
      "available": true,
      "details": {
        "revert_rate": 0.35,
        "mev_incident_rate": 0.12,
        "data_source": "gina",
        "observation_period_days": 90,
        "sample_size": 4600
      }
    }
  },
  "metadata": {
    "inputs_provided": ["wallet_address", "domain"],
    "latency_ms": 1100,
    "version": "0.2.0"
  }
}
```

## Implementation Timeline

| Week | Milestone | Owner |
|------|-----------|-------|
| **Week 1** | Define webhook schema for failure event ingestion | Both |
| **Week 1** | Gina exports historical failure dataset (18 months) | Gina |
| **Week 2** | Revettr ingests historical data, builds initial signal models | Revettr |
| **Week 2** | Define `defi_execution` signal group and scoring weights | Revettr |
| **Week 3** | Gina integrates pre-execution check between Filter and Executor | Gina |
| **Week 3** | Revettr deploys DeFi signal scores in API responses | Revettr |
| **Week 4** | Daily failure event webhook goes live | Gina |
| **Week 4** | Dynamic threshold configuration exposed via Gina operator settings | Gina |
| **Week 5** | Monitoring, alerting, and model accuracy evaluation | Both |
| **Week 6** | Public announcement, documentation update | Both |

## Data Privacy and Security

- Gina failure data is used solely for scoring model improvement
- No end-user PII is included in failure events (only wallet addresses and tx hashes)
- Gina can redact any fields before sending
- Data retention: Revettr retains aggregated signals indefinitely; raw failure events
  are retained for 12 months, then purged
- Gina can request deletion of all submitted data with 30 days notice

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| False positive rate (blocked good txns) | < 5% | Compare blocked txns against manual review |
| True positive rate (caught bad txns) | > 70% | Compare flagged counterparties against actual failures |
| Gina failure rate reduction | 30%+ | Compare pre/post integration failure rates |
| Score latency p95 | < 2 seconds | Measured at Gina's integration point |
| Data freshness | < 24 hours | Time from Gina failure event to Revettr signal update |
