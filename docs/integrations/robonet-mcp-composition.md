# Robonet x Revettr: MCP Server Composition

**Version**: 1.0
**Date**: 2026-04-02
**Status**: Draft
**Partners**: Robonet (DeFi Strategy MCP), Revettr (Counterparty Risk Scoring MCP)

## Overview

Robonet operates 7 specialized DeFi agents backed by 30+ MCP tools covering yield
farming, liquidity provision, vault deployment, rebalancing, and more. Revettr
provides counterparty risk scoring as a single MCP tool (`score_counterparty`).

When both MCP servers run side-by-side in a client like Claude Desktop, Cursor, or
a custom agent, the LLM can compose their tools naturally: discover a strategy with
Robonet, score the vault or protocol with Revettr, then deploy or reject based on
trust. No custom integration code is needed -- MCP composition handles it.

This document shows how to configure both servers, wire them into agent workflows,
and enforce a "score before deploy" policy via system prompts.

## MCP Client Configuration

### Claude Code (`~/.claude.json`)

```json
{
  "mcpServers": {
    "revettr": {
      "command": "uvx",
      "args": ["revettr-mcp"],
      "env": {
        "REVETTR_WALLET_KEY": "${REVETTR_WALLET_KEY}"
      }
    },
    "robonet": {
      "command": "npx",
      "args": ["-y", "@robonet/mcp-server"],
      "env": {
        "ROBONET_API_KEY": "${ROBONET_API_KEY}",
        "ROBONET_NETWORK": "base"
      }
    }
  }
}
```

### Cursor (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "revettr": {
      "command": "uvx",
      "args": ["revettr-mcp"],
      "env": {
        "REVETTR_WALLET_KEY": "${REVETTR_WALLET_KEY}"
      }
    },
    "robonet": {
      "command": "npx",
      "args": ["-y", "@robonet/mcp-server"],
      "env": {
        "ROBONET_API_KEY": "${ROBONET_API_KEY}",
        "ROBONET_NETWORK": "base"
      }
    }
  }
}
```

### Remote HTTP Transport (Streamable HTTP)

For server-side deployments where both MCP servers run as remote services:

```json
{
  "mcpServers": {
    "revettr": {
      "type": "streamable-http",
      "url": "https://mcp.revettr.com/sse",
      "headers": {
        "Authorization": "Bearer ${REVETTR_MCP_TOKEN}"
      }
    },
    "robonet": {
      "type": "streamable-http",
      "url": "https://mcp.robonet.ai/sse",
      "headers": {
        "Authorization": "Bearer ${ROBONET_MCP_TOKEN}"
      }
    }
  }
}
```

Remote transport is preferred for production agents that run on servers (no local
`uvx` / `npx` processes). Both servers expose Streamable HTTP endpoints that
MCP clients connect to over HTTPS.

## Agent Flow: Score Before Deploy

The core pattern is a 4-step flow that any MCP-capable agent follows:

```
Step 1: DISCOVER              Step 2: SCORE
+---------------------+      +---------------------+
| Robonet tools:      |      | Revettr tool:       |
|                     |      |                     |
| discover_strategies |----->| score_counterparty  |
| get_vault_details   |      |   wallet_address    |
| estimate_yield      |      |   domain            |
|                     |      |   chain              |
+---------------------+      +----------+----------+
                                         |
                                    score >= 60?
                                    /          \
                                  YES           NO
                                   |             |
                                   v             v
                    Step 3: DEPLOY        Step 4: EXPLAIN
              +---------------------+  +---------------------+
              | Robonet tools:      |  | Agent explains:     |
              |                     |  |                     |
              | deploy_to_vault     |  | "Vault scored 35    |
              | set_rebalance_rules |  |  (high risk) due    |
              | confirm_position    |  |  to flags: ..."     |
              +---------------------+  +---------------------+
```

### Detailed Step-by-Step

**Step 1: Discover strategy**

The agent (or user) asks for yield opportunities. Robonet tools handle this:

```
User: "Find me the best ETH yield vault on Base"

Agent calls: robonet.discover_strategies(
    asset="ETH",
    chain="base",
    strategy_type="vault",
    sort_by="apy"
)

Response: [
    {name: "Morpho ETH Vault", apy: 8.2%, vault: "0xabc...", domain: "morpho.org"},
    {name: "NewYield ETH", apy: 12.1%, vault: "0xdef...", domain: "newyield.xyz"},
    ...
]
```

**Step 2: Score the counterparty**

Before deploying to any vault, the agent scores it with Revettr:

```
Agent calls: revettr.score_counterparty(
    wallet_address="0xdef...",
    domain="newyield.xyz",
    chain="base"
)

Response: {
    score: 35,
    tier: "high",
    flags: ["domain_age_under_30d", "wallet_age_under_7d"],
    confidence: 0.65
}
```

**Step 3: Gate the decision**

The agent applies the scoring policy:

- Score >= 60: proceed to deploy
- Score < 60: explain the risk and suggest alternatives

```
Agent: "NewYield ETH vault (12.1% APY) scored 35/100 -- high risk.
Flags: domain is less than 30 days old, wallet has less than 7 days
of history. I recommend the Morpho ETH Vault instead. Let me score it."

Agent calls: revettr.score_counterparty(
    wallet_address="0xabc...",
    domain="morpho.org",
    chain="base"
)

Response: {score: 92, tier: "low", flags: [], confidence: 0.85}

Agent: "Morpho ETH Vault scored 92/100 (low risk). 8.2% APY.
Shall I deploy?"
```

**Step 4: Deploy or explain**

If approved, the agent calls Robonet deployment tools:

```
Agent calls: robonet.deploy_to_vault(
    vault_address="0xabc...",
    amount_eth=1.0,
    chain="base"
)
```

## System Prompt Template

To enforce the "always score before deploying" policy, include this in the agent's
system prompt. This works with any MCP client that supports system prompts (Claude
Desktop, Cursor, custom agents):

```
You have access to two MCP tool servers:

1. **Robonet** -- DeFi strategy discovery and execution
   Tools: discover_strategies, get_vault_details, estimate_yield,
   deploy_to_vault, set_rebalance_rules, withdraw_position, and more.

2. **Revettr** -- Counterparty risk scoring
   Tool: score_counterparty (accepts domain, wallet_address, chain)

MANDATORY POLICY: Before calling ANY Robonet tool that moves funds
(deploy_to_vault, set_rebalance_rules, swap, bridge, or any tool
that triggers an on-chain transaction), you MUST first call
revettr.score_counterparty with the target contract's wallet address
and domain.

Scoring rules:
- Score 80-100 (low risk): Safe to proceed. Inform the user of the score.
- Score 60-79 (medium risk): Proceed with caution. Warn the user about
  any flags and ask for explicit confirmation before deploying.
- Score 30-59 (high risk): DO NOT deploy. Explain the risk flags to the
  user and suggest alternatives.
- Score 0-29 (critical risk): DO NOT deploy. This counterparty has
  severe risk indicators. Explain why and refuse the transaction.

If Revettr is unavailable (timeout, error), DO NOT proceed with
deployment. Inform the user that the risk check could not be completed.

Always show the user: score, tier, confidence, and any flags before
asking for deployment confirmation.
```

## Cost Model

| Action | Tool | Cost |
|--------|------|------|
| Discover strategies | `robonet.discover_strategies` | Free (read-only) |
| Get vault details | `robonet.get_vault_details` | Free (read-only) |
| Estimate yield | `robonet.estimate_yield` | Free (read-only) |
| Score counterparty | `revettr.score_counterparty` | $0.01 USDC (x402) |
| Deploy to vault | `robonet.deploy_to_vault` | $0.02 USDC (Robonet fee) |
| Set rebalance rules | `robonet.set_rebalance_rules` | $0.01 USDC (Robonet fee) |

**Per deployment decision cost**: $0.01 (Revettr score) + $0.01-$0.02 (Robonet
execution) = **$0.02-$0.03 total**.

At scale, an agent making 100 deployment decisions per day pays $2-$3/day for
trust-gated DeFi execution. This is negligible compared to the value at risk in
each deployment.

### Cost Optimization

- **Cache scores**: Revettr scores are valid for 24h. If the agent scores the same
  vault multiple times in a session, the MCP client can cache the first result.
- **Batch discovery**: Score multiple vaults in parallel before presenting options
  to the user, rather than scoring one at a time.
- **Skip scoring for known vaults**: Maintain a local allowlist of vault addresses
  that have been scored recently and consistently score >= 80.

## Example: Full Conversation

```
User: I have 5 ETH. Find me the best yield on Base.

Agent: I'll search for ETH yield strategies on Base.

[Calls robonet.discover_strategies(asset="ETH", chain="base", sort_by="apy")]

Found 4 strategies:
1. NewYield ETH Vault -- 12.1% APY (0xdef...)
2. Morpho Blue ETH -- 8.2% APY (0xabc...)
3. Aave v3 ETH -- 4.8% APY (0x111...)
4. Compound III ETH -- 4.1% APY (0x222...)

Let me check the risk profile of the top options before recommending one.

[Calls revettr.score_counterparty(wallet_address="0xdef...",
    domain="newyield.xyz", chain="base")]
[Calls revettr.score_counterparty(wallet_address="0xabc...",
    domain="morpho.org", chain="base")]

Risk assessment:

| Vault | APY | Score | Tier | Flags |
|-------|-----|-------|------|-------|
| NewYield | 12.1% | 35 | high | domain_age_under_30d, wallet_age_under_7d |
| Morpho Blue | 8.2% | 92 | low | (none) |

I do NOT recommend NewYield despite the higher APY. The domain is
less than 30 days old and the contract wallet has less than 7 days
of on-chain history. These are strong risk signals.

Morpho Blue scored 92/100 (low risk) with no flags. The 8.2% APY
is solid and the protocol has a strong trust profile.

Shall I deploy 5 ETH to Morpho Blue?

User: Yes, go ahead.

[Calls robonet.deploy_to_vault(vault_address="0xabc...",
    amount_eth=5.0, chain="base")]

Done. 5 ETH deployed to Morpho Blue ETH vault on Base.
- Estimated APY: 8.2%
- Risk score: 92/100 (low)
- Transaction: 0x789...
```

## Advanced: Multi-Agent Orchestration

For Robonet deployments with multiple specialized agents (e.g., a yield agent, a
rebalancing agent, and a risk monitoring agent), Revettr can serve as the shared
risk layer:

```
+-------------------+     +-------------------+     +-------------------+
|  Yield Agent      |     | Rebalance Agent   |     | Monitor Agent     |
|  (discovers,      |     | (adjusts          |     | (watches          |
|   deploys)        |     |  positions)       |     |  positions)       |
+--------+----------+     +--------+----------+     +--------+----------+
         |                         |                         |
         |   score_counterparty    |   score_counterparty    |  (reads cached)
         +------------+------------+------------+------------+
                      |                         |
                      v                         v
              +-------+-------------------------+-------+
              |              Revettr MCP                 |
              |   (shared risk scoring for all agents)   |
              +-----------------------------------------+
```

Each Robonet agent independently calls `score_counterparty` before any fund-moving
action. The scoring is stateless -- no coordination between agents is needed. If
Revettr flags a vault as risky, the rebalancing agent will refuse to increase
exposure to it, even if the yield agent originally deployed there when the score
was higher.

## Error Handling

| Scenario | Agent Behavior |
|----------|----------------|
| Revettr MCP unavailable | Do not deploy. Inform user: "Risk check unavailable. Cannot proceed." |
| Revettr returns error | Retry once. If still failing, do not deploy. |
| Robonet MCP unavailable | Cannot discover or deploy. Inform user. |
| Score is borderline (55-65) | Show user the score and flags. Ask for explicit confirmation. |
| Both servers healthy but score is critical | Refuse deployment. Suggest the user research the protocol independently. |

## Security Notes

- `REVETTR_WALLET_KEY` funds x402 payments. Store in environment variables or a
  secrets manager. Never hardcode in config files checked into version control.
- `ROBONET_API_KEY` authenticates with Robonet. Same storage guidance applies.
- For remote HTTP transport, MCP tokens should be rotated regularly.
- The system prompt policy is enforced by the LLM, not by code. For hard enforcement,
  wrap Robonet's fund-moving tools in a middleware that calls Revettr programmatically.
