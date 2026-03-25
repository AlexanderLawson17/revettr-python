# Revettr

Counterparty risk scoring for agentic commerce. One API call answers: **"Should this agent send money to this counterparty?"**

Revettr scores counterparties by analyzing domain intelligence, IP reputation, on-chain wallet history, and sanctions lists. It's designed for AI agents transacting via [x402](https://x402.org) on Base.

[![revettr MCP server](https://glama.ai/mcp/servers/AlexanderLawson17/revettr-python/badges/card.svg)](https://glama.ai/mcp/servers/AlexanderLawson17/revettr-python)

## Install

```bash
pip install revettr
```

## Quick Start

```python
from revettr import Revettr

client = Revettr()

# Score a counterparty — send whatever data you have
score = client.score(
    domain="uniswap.org",
    ip="104.18.28.72",
    wallet_address="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
)

print(f"Score: {score.score}/100 ({score.tier})")
print(f"Confidence: {score.confidence}")
print(f"Flags: {score.flags}")

if score.tier == "critical":
    print("DO NOT TRANSACT")
```

## What Gets Scored

Send any combination of inputs. More data = higher confidence.

| Input | Signal Group | What It Checks |
|-------|-------------|----------------|
| `domain` | Domain Intelligence | WHOIS age, DNS config (MX, SPF, DMARC), SSL certificate |
| `ip` | IP Intelligence | Geolocation, VPN/proxy/Tor detection, datacenter vs residential |
| `wallet_address` | Wallet Analysis | Transaction count, wallet age, counterparty diversity, on-chain behavior |
| `company_name` | Sanctions Screening | OFAC SDN, EU consolidated, UN consolidated sanctions lists |

## Response

```json
{
  "score": 90,
  "tier": "low",
  "confidence": 0.75,
  "signals_checked": 3,
  "flags": [],
  "signal_scores": {
    "domain": {
      "score": 80,
      "flags": [],
      "available": true,
      "details": {
        "domain_age_days": 2673,
        "dns": {"has_mx": true, "has_spf": true, "has_dmarc": true}
      }
    },
    "ip": {
      "score": 100,
      "flags": [],
      "available": true,
      "details": {
        "country": "US",
        "asn_org": "Cloudflare, Inc.",
        "is_private": false
      }
    },
    "wallet": {
      "score": 100,
      "flags": [],
      "available": true,
      "details": {
        "alchemy": {"tx_count": 100, "unique_counterparties": 29},
        "rpc": {"nonce": 16, "eth_balance": 0.072}
      }
    }
  },
  "metadata": {
    "inputs_provided": ["domain", "ip", "wallet_address"],
    "latency_ms": 1185,
    "version": "0.1.0"
  }
}
```

## Score Tiers

| Score | Tier | Meaning |
|-------|------|---------|
| 80-100 | `low` | Counterparty appears legitimate |
| 60-79 | `medium` | Some signals warrant caution |
| 30-59 | `high` | Multiple risk indicators present |
| 0-29 | `critical` | Strong risk signals — do not transact |

A score of **0** means a hard match (e.g., exact sanctions hit). This overrides all other signals.

## Risk Flags

Flags tell you exactly what triggered a score reduction:

| Flag | Signal | Meaning |
|------|--------|---------|
| `domain_age_under_7_days` | Domain | Domain registered less than 7 days ago |
| `domain_age_under_30_days` | Domain | Domain registered less than 30 days ago |
| `no_mx_records` | Domain | Domain has no email server configured |
| `no_spf_record` | Domain | No SPF email authentication |
| `ssl_invalid_or_expired` | Domain | SSL certificate is invalid or expired |
| `ssl_self_signed` | Domain | Self-signed SSL certificate |
| `tor_exit_node` | IP | IP is a known Tor exit node |
| `known_vpn` | IP | IP belongs to a known VPN provider |
| `datacenter_ip` | IP | IP is from a datacenter (not residential) |
| `high_risk_country_XX` | IP | IP geolocates to a sanctioned country |
| `wallet_never_transacted` | Wallet | Wallet has zero transactions (nonce = 0) |
| `wallet_created_today` | Wallet | Wallet's first transaction was today |
| `wallet_age_under_7_days` | Wallet | Wallet is less than 7 days old |
| `wallet_few_counterparties` | Wallet | Wallet has interacted with fewer than 3 addresses |
| `wallet_mixer_exposure` | Wallet | Wallet has interacted with known mixers |
| `wallet_sanctioned` | Wallet | Wallet appears on a sanctions list |
| `sanctions_exact_match` | Sanctions | Exact name match on OFAC/EU/UN sanctions list |
| `sanctions_high_confidence_match` | Sanctions | High confidence fuzzy match on sanctions list |

## Usage Examples

### Wallet only (minimal)

```python
score = client.score(wallet_address="0xabc...")
```

### Domain + IP (web service check)

```python
score = client.score(domain="some-api.xyz", ip="185.220.101.42")
```

### Full check

```python
score = client.score(
    domain="merchant.com",
    ip="104.18.28.72",
    wallet_address="0xabc...",
    company_name="Merchant LLC",
)
```

### With x402 auto-payment

The client handles x402 payment automatically. You need a funded wallet:

```python
from revettr import Revettr

client = Revettr(
    wallet_private_key="0xYOUR_PRIVATE_KEY",  # Wallet that pays for the API call
)

# Client automatically handles the 402 → payment → retry flow
score = client.score(wallet_address="0xabc...")
```

## Pricing

| Tier | Price | What You Get |
|------|-------|-------------|
| Standard | $0.01 USDC | All available signals based on inputs provided |

Payment is via [x402](https://x402.org) protocol — USDC on Base network. No API keys, no accounts, no contracts.

## API Reference

### `POST /v1/score`

**Payment**: x402 — $0.01 USDC on Base per request

**Request body** (JSON):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `domain` | string | No | Domain or URL |
| `ip` | string | No | IPv4 address |
| `wallet_address` | string | No | EVM address (0x...) |
| `chain` | string | No | Blockchain network (default: `base`) |
| `company_name` | string | No | Name to screen against sanctions |
| `email` | string | No | Email (future — not scored yet) |
| `amount` | float | No | Transaction amount in USD (context only) |

At least one of `domain`, `ip`, `wallet_address`, or `company_name` is required.

### `GET /health`

**Payment**: None (always free)

Returns API status and signal source availability.

## Direct HTTP (without SDK)

```bash
# Without payment (returns 402):
curl -X POST https://revettr.com/v1/score \
  -H "Content-Type: application/json" \
  -d '{"domain": "example.com"}'

# Returns HTTP 402 with payment-required header containing x402 payment terms
```

## Disclaimer

Revettr is an **informational tool**. It aggregates publicly available signals and returns a risk score. It is **not** a compliance certification, legal advice, or guarantee of counterparty legitimacy. You are responsible for your own transaction decisions.

## Built by

[L Squared Digital Holdings](https://revettr.com)