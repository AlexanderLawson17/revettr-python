# Bankr x Revettr Integration Specification

**Version**: 1.0
**Date**: 2026-04-02
**Status**: Draft
**Partners**: Bankr (x402 Cloud), Revettr (Counterparty Risk Scoring)

## Overview

Bankr operates the x402 Cloud discovery layer -- indexing x402-enabled endpoints so
AI agents can find and evaluate services before transacting. Today, Bankr's discovery
responses include endpoint metadata (pricing, capabilities, uptime) but lack
counterparty trust data. Agents must make payment decisions without knowing whether the
endpoint operator is trustworthy.

This integration embeds Revettr risk scores directly into Bankr's discovery index.
When an endpoint registers with Bankr, the indexer calls Revettr to score the
operator's wallet, domain, and chain presence. The resulting score, tier, and flags
are cached alongside the endpoint metadata. Agents querying Bankr's discovery API
receive trust data inline -- no extra call required.

The result: agents can filter and rank x402 endpoints by trust before spending a
single cent.

## Architecture

```
+-------------------+       +-------------------+       +-------------------+
|   x402 Endpoint   |       |       Bankr       |       |      Revettr      |
|   (registers)     |       |   (discovery)     |       |   (risk scoring)  |
+--------+----------+       +--------+----------+       +--------+----------+
         |                           |                           |
         | 1. POST /register         |                           |
         |   {url, wallet, domain,   |                           |
         |    capabilities, pricing} |                           |
         +-------------------------->|                           |
         |                           |                           |
         |                           | 2. POST /v1/score         |
         |                           |   {wallet_address,        |
         |                           |    domain, chain}         |
         |                           +-------------------------->|
         |                           |                           |
         |                           | 3. Response               |
         |                           |   {score, tier, flags,    |
         |                           |    confidence}            |
         |                           |<--------------------------+
         |                           |                           |
         |                           | 4. Cache score in index   |
         |                           |   (24h TTL)               |
         |                           |                           |
         |                           |                           |
+-------------------+                |                           |
|    Agent          |                |                           |
|    (queries)      |                |                           |
+--------+----------+                |                           |
         |                           |                           |
         | 5. GET /discover          |                           |
         |   ?capability=swap        |                           |
         +-------------------------->|                           |
         |                           |                           |
         | 6. Response with          |                           |
         |   enriched listings       |                           |
         |   (includes revettr_*)    |                           |
         |<--------------------------+                           |
         |                           |                           |
```

## API Contract

### Scoring at Index Time

When Bankr indexes a new or updated endpoint, it calls Revettr's scoring API:

**Request**: `POST https://revettr.com/v1/score`

```json
{
  "wallet_address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
  "domain": "swap-api.example.com",
  "chain": "base"
}
```

**Response** (HTTP 200):

```json
{
  "score": 85,
  "tier": "low",
  "confidence": 0.75,
  "signals_checked": 2,
  "flags": [],
  "signal_scores": {
    "domain": {
      "score": 80,
      "flags": [],
      "available": true,
      "details": {
        "domain_age_days": 1200,
        "dns": {"has_mx": true, "has_spf": true, "has_dmarc": true}
      }
    },
    "wallet": {
      "score": 90,
      "flags": [],
      "available": true,
      "details": {
        "blockchain": {"tx_count": 500, "unique_counterparties": 87},
        "onchain": {"nonce": 312, "eth_balance": 1.45}
      }
    }
  },
  "metadata": {
    "inputs_provided": ["wallet_address", "domain"],
    "latency_ms": 980,
    "version": "0.1.0"
  }
}
```

**Payment**: $0.01 USDC per request via x402 on Base. Bankr's indexer wallet pays
automatically using the x402 protocol.

### Discovery Response Enrichment

Bankr adds three fields to each endpoint listing in discovery responses:

| Field | Type | Description |
|-------|------|-------------|
| `revettr_score` | `int` (0-100) | Composite risk score. Higher is safer. |
| `revettr_tier` | `string` | Risk tier: `low` (80-100), `medium` (60-79), `high` (30-59), `critical` (0-29) |
| `revettr_flags` | `list[string]` | Machine-readable risk flags (e.g., `domain_age_under_30d`, `wallet_never_transacted`) |

Example enriched discovery response:

```json
{
  "endpoints": [
    {
      "url": "https://swap-api.example.com/v1/swap",
      "wallet": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
      "capability": "swap",
      "chain": "base",
      "price_usdc": 0.05,
      "uptime_30d": 0.997,
      "revettr_score": 85,
      "revettr_tier": "low",
      "revettr_flags": []
    },
    {
      "url": "https://shady-swap.xyz/api",
      "wallet": "0xabc123...",
      "capability": "swap",
      "chain": "base",
      "price_usdc": 0.02,
      "uptime_30d": 0.91,
      "revettr_score": 28,
      "revettr_tier": "critical",
      "revettr_flags": ["domain_age_under_30d", "wallet_age_under_7d", "no_mx_records"]
    }
  ]
}
```

### Batch Enrichment

For bulk indexing runs (new chain onboarding, periodic re-index), Bankr can use the
batch scoring endpoint to reduce latency and per-request overhead:

**Request**: `POST https://revettr.com/v1/score_batch`

```json
{
  "requests": [
    {"wallet_address": "0xaaa...", "domain": "api-a.com", "chain": "base"},
    {"wallet_address": "0xbbb...", "domain": "api-b.com", "chain": "base"},
    {"wallet_address": "0xccc...", "domain": "api-c.com", "chain": "base"}
  ]
}
```

**Response** (HTTP 200):

```json
{
  "results": [
    {"score": 85, "tier": "low", "flags": [], "confidence": 0.75},
    {"score": 62, "tier": "medium", "flags": ["wallet_age_under_30d"], "confidence": 0.60},
    {"score": 15, "tier": "critical", "flags": ["sanctions_exact_match"], "confidence": 1.0}
  ],
  "metadata": {
    "batch_size": 3,
    "latency_ms": 2100
  }
}
```

**Pricing**: $0.01 USDC per item in the batch. Max batch size: 100.

## Score Refresh Policy

Scores are not static. The refresh policy balances freshness against cost:

| Trigger | Action |
|---------|--------|
| **Stale threshold** | Re-score any endpoint whose cached score is older than 24 hours |
| **Wallet change detected** | If Bankr detects the endpoint's wallet address changed, re-score immediately |
| **Domain change detected** | If the endpoint's domain or IP changes, re-score immediately |
| **Agent-requested refresh** | Agent passes `?refresh_score=true` on discovery query; Bankr re-scores before responding |
| **Manual flag** | Bankr admin can force re-score via internal tooling |

Bankr should store `revettr_scored_at` (ISO 8601 timestamp) alongside each cached
score to implement TTL-based expiry.

## Feedback Loop

To improve scoring accuracy over time, Bankr can report transaction outcomes back
to Revettr. This creates a supervised signal: real-world success/failure data tied
to scored counterparties.

### Proposed Endpoint

**Request**: `POST https://revettr.com/v1/feedback`

```json
{
  "wallet_address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
  "domain": "swap-api.example.com",
  "chain": "base",
  "outcome": "success",
  "tx_hash": "0x789abc...",
  "amount_usdc": 0.05,
  "latency_ms": 1200,
  "agent_id": "bankr-discovery-v1"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `wallet_address` | string | Yes | The scored counterparty wallet |
| `domain` | string | No | The scored domain |
| `chain` | string | No | Blockchain network |
| `outcome` | string | Yes | `success`, `failure`, `timeout`, `reverted` |
| `tx_hash` | string | No | On-chain transaction hash for verification |
| `amount_usdc` | float | No | Transaction value |
| `latency_ms` | int | No | End-to-end transaction time |
| `agent_id` | string | No | Identifier for the reporting agent/system |

**Response** (HTTP 200):

```json
{
  "accepted": true,
  "feedback_id": "fb_abc123"
}
```

This endpoint is free -- no x402 payment required. Outcome data is the payment.

## Business Model

Two options for the Bankr partnership:

### Option A: Free Scoring for Outcome Data

- Bankr scores endpoints at no cost (Revettr waives the $0.01/score fee)
- In exchange, Bankr sends all transaction outcome data via the feedback endpoint
- Revettr uses this labeled data to improve scoring models
- Best for: early partnership phase, mutual growth

### Option B: Volume Pricing

- Standard rate: $0.01 USDC per score via x402
- Volume tiers (monthly):
  - 0-10,000 scores: $0.01/score
  - 10,001-100,000: $0.008/score
  - 100,001+: $0.005/score
- Feedback endpoint remains free regardless of tier
- Best for: scaled operations where outcome data alone is insufficient

Recommendation: Start with Option A during the integration phase (first 90 days),
then evaluate whether to transition to Option B based on volume.

## Agent Decision Flow

Python code sample showing how an agent uses Bankr's enriched discovery to make
trust-aware decisions:

```python
import httpx
from revettr import Revettr

# Agent discovers x402 endpoints via Bankr
async def find_trusted_swap_endpoint(token_pair: str, max_price: float) -> dict | None:
    """Find the most trusted, affordable swap endpoint."""

    async with httpx.AsyncClient() as client:
        # Query Bankr discovery with capability filter
        resp = await client.get(
            "https://bankr.cloud/discover",
            params={"capability": "swap", "token_pair": token_pair},
        )
        endpoints = resp.json()["endpoints"]

    # Filter: only endpoints scoring >= 60 (exclude high and critical risk)
    trusted = [ep for ep in endpoints if ep.get("revettr_score", 0) >= 60]

    # Filter: within budget
    affordable = [ep for ep in trusted if ep["price_usdc"] <= max_price]

    if not affordable:
        return None

    # Sort: highest trust score first, then lowest price
    affordable.sort(key=lambda ep: (-ep["revettr_score"], ep["price_usdc"]))

    return affordable[0]


# Usage in an agent loop
async def execute_swap(token_pair: str, amount: float):
    endpoint = await find_trusted_swap_endpoint(token_pair, max_price=0.10)

    if endpoint is None:
        print("No trusted endpoint found within budget")
        return

    print(f"Selected: {endpoint['url']}")
    print(f"  Trust: {endpoint['revettr_score']}/100 ({endpoint['revettr_tier']})")
    print(f"  Price: ${endpoint['price_usdc']} USDC")
    print(f"  Flags: {endpoint.get('revettr_flags', [])}")

    # If any flags are present, log them for the agent operator
    if endpoint.get("revettr_flags"):
        print(f"  Warning: {len(endpoint['revettr_flags'])} risk flag(s) noted")

    # Proceed with x402 payment to the endpoint
    # ... (x402 payment flow here)
```

## Implementation Timeline

| Week | Milestone | Owner |
|------|-----------|-------|
| **Week 1** | Bankr indexer calls `POST /v1/score` on new registrations; cache score with 24h TTL | Bankr |
| **Week 1** | Revettr provisions Bankr indexer wallet for x402 payments (or activates Option A waiver) | Revettr |
| **Week 2** | Discovery API returns `revettr_score`, `revettr_tier`, `revettr_flags` in listings | Bankr |
| **Week 2** | Batch endpoint (`/v1/score_batch`) deployed for bulk indexing | Revettr |
| **Week 3** | Score refresh logic: 24h stale check, wallet/domain change triggers | Bankr |
| **Week 3** | Feedback endpoint (`/v1/feedback`) deployed | Revettr |
| **Week 4** | Bankr sends transaction outcomes via feedback loop | Bankr |
| **Week 4** | End-to-end testing, monitoring, launch | Both |

## Error Handling

| Scenario | Bankr Behavior |
|----------|----------------|
| Revettr returns HTTP 402 | Retry with x402 payment; if wallet balance is insufficient, index without score and flag for manual review |
| Revettr returns HTTP 5xx | Retry once after 2s; if still failing, index without score, set `revettr_score: null` |
| Revettr timeout (>10s) | Index without score, queue for async re-score |
| Score is `critical` (0-29) | Index the endpoint but mark it with a warning badge in discovery UI |
| Sanctions flag present | Do not index the endpoint; notify Bankr compliance team |

## Security Considerations

- Bankr's indexer wallet private key must be stored in a secrets manager, never in code
- All Revettr API calls use HTTPS (enforced by the SDK)
- Feedback data should not include PII -- only wallet addresses, domains, and tx hashes
- Bankr should rate-limit discovery queries that include `?refresh_score=true` to
  prevent score-refresh abuse
