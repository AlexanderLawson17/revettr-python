"""Example: Virtuals ACP buyer agent with Revettr counterparty risk checking.

Before creating a job with a seller agent on Virtuals' Agent Commerce Protocol,
this buyer checks the seller's wallet via Revettr to assess counterparty risk.

Virtuals ACP (https://app.virtuals.io/acp) enables agent-to-agent commerce where
AI agents discover, hire, and pay each other via smart contracts on Base. This
example adds a pre-job risk layer so buyer agents don't send funds to risky sellers.

Usage:
    pip install revettr virtuals-acp
    export REVETTR_WALLET_KEY="0x..."       # For x402 payment (or use free tier)
    export WHITELISTED_WALLET_PRIVATE_KEY="0x..."
    export BUYER_AGENT_WALLET_ADDRESS="0x..."
    export BUYER_ENTITY_ID="123"
    export EVALUATOR_AGENT_WALLET_ADDRESS="0x..."
    python examples/virtuals_acp_safe_buyer.py
"""

import logging
import os
import time

from revettr import Revettr

# --- ACP imports (uncomment when running with real ACP credentials) ---
# from dotenv import load_dotenv
# from virtuals_acp.client import VirtualsACP
# from virtuals_acp.configs.configs import BASE_MAINNET_ACP_X402_CONFIG_V2
# from virtuals_acp.contract_clients.contract_client_v2 import ACPContractClientV2
# from virtuals_acp.env import EnvSettings
# from virtuals_acp.job import ACPJob
# from virtuals_acp.models import (
#     ACPGraduationStatus,
#     ACPJobPhase,
#     ACPOnlineStatus,
# )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("SafeBuyerAgent")

# Minimum Revettr score to proceed with a job (0-100).
# 60+ = "low" or "medium" risk — safe to transact.
# Below 60 = "high" or "critical" risk — block the job.
MIN_SCORE = 60

POLL_INTERVAL_SECONDS = 20


def check_seller_risk(seller_wallet: str, min_score: int = MIN_SCORE) -> dict:
    """Score a Virtuals ACP seller's wallet before creating a job.

    Returns a dict with:
        decision: "proceed" | "warn" | "block"
        score: int (0-100) or None on error
        tier: str risk tier
        flags: list of risk flags
        reason: human-readable explanation
    """
    client = Revettr(
        wallet_private_key=os.getenv("REVETTR_WALLET_KEY"),  # Optional for free tier
    )

    try:
        result = client.score(wallet_address=seller_wallet)

        if result.score >= min_score:
            return {
                "decision": "proceed",
                "score": result.score,
                "tier": result.tier,
                "flags": result.flags,
                "reason": (
                    f"Seller scored {result.score}/100 ({result.tier} risk) "
                    f"-- safe to create job."
                ),
            }
        elif result.score >= 30:
            return {
                "decision": "warn",
                "score": result.score,
                "tier": result.tier,
                "flags": result.flags,
                "reason": (
                    f"Seller scored {result.score}/100 ({result.tier} risk). "
                    f"Proceed with caution."
                ),
            }
        else:
            return {
                "decision": "block",
                "score": result.score,
                "tier": result.tier,
                "flags": result.flags,
                "reason": (
                    f"Seller scored {result.score}/100 ({result.tier} risk). "
                    f"Do NOT create job."
                ),
            }
    except Exception as e:
        # If Revettr is unreachable, degrade gracefully — don't block all commerce.
        return {
            "decision": "warn",
            "score": None,
            "tier": "unknown",
            "flags": [],
            "reason": f"Could not score seller: {e}. Proceed with caution.",
        }


def safe_buyer():
    """ACP buyer flow with Revettr risk check before job creation.

    The flow:
    1. Browse agents via ACP Service Registry
    2. Pick a seller based on your criteria
    3. Score the seller's wallet via Revettr
    4. Only initiate the job if the seller passes the risk check
    5. Poll for job completion (standard ACP buyer loop)
    """

    # ----------------------------------------------------------------
    # ACP initialization (uncomment with real credentials)
    # ----------------------------------------------------------------
    # load_dotenv(override=True)
    # env = EnvSettings()
    #
    # acp_client = VirtualsACP(
    #     acp_contract_clients=ACPContractClientV2(
    #         wallet_private_key=env.WHITELISTED_WALLET_PRIVATE_KEY,
    #         agent_wallet_address=env.BUYER_AGENT_WALLET_ADDRESS,
    #         entity_id=env.BUYER_ENTITY_ID,
    #         config=BASE_MAINNET_ACP_X402_CONFIG_V2,
    #     ),
    # )
    #
    # logger.info(f"Buyer ACP initialized. Agent: {acp_client.wallet_address}")

    # ----------------------------------------------------------------
    # Step 1: Discover sellers via ACP Service Registry
    # ----------------------------------------------------------------
    # relevant_agents = acp_client.browse_agents(
    #     keyword="data analysis",
    #     graduation_status=ACPGraduationStatus.ALL,
    #     online_status=ACPOnlineStatus.ONLINE,
    #     top_k=5,
    # )
    #
    # if not relevant_agents:
    #     logger.warning("No matching agents found.")
    #     return
    #
    # chosen_agent = relevant_agents[0]
    # seller_wallet = chosen_agent.wallet_address

    # For this example, simulate a discovered seller:
    seller_wallet = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
    logger.info(f"Found seller agent: {seller_wallet}")

    # ----------------------------------------------------------------
    # Step 2: Check counterparty risk BEFORE creating a job
    # ----------------------------------------------------------------
    logger.info("Checking seller counterparty risk via Revettr...")
    risk = check_seller_risk(seller_wallet, min_score=MIN_SCORE)

    logger.info(f"Risk assessment:")
    logger.info(f"  Decision : {risk['decision'].upper()}")
    logger.info(f"  Score    : {risk['score']}/100 ({risk['tier']})")
    logger.info(f"  Flags    : {', '.join(risk['flags']) if risk['flags'] else 'none'}")
    logger.info(f"  Reason   : {risk['reason']}")

    if risk["decision"] == "block":
        logger.error("Job creation BLOCKED -- seller is too risky.")
        return

    if risk["decision"] == "warn":
        logger.warning("Proceeding with caution -- seller has elevated risk.")

    # ----------------------------------------------------------------
    # Step 3: Create the ACP job (only if risk check passes)
    # ----------------------------------------------------------------
    # chosen_offering = chosen_agent.job_offerings[0]
    #
    # job_id = chosen_offering.initiate_job(
    #     service_requirement={
    #         "task": "Analyze Q1 sales data",
    #         "format": "csv",
    #     },
    #     evaluator_address=env.EVALUATOR_AGENT_WALLET_ADDRESS,
    # )
    #
    # logger.info(f"Job {job_id} initiated with risk-checked seller.")

    logger.info(
        f"Risk check passed -- safe to create ACP job with {seller_wallet[:10]}..."
    )

    # ----------------------------------------------------------------
    # Step 4: Standard ACP buyer polling loop
    # ----------------------------------------------------------------
    # while True:
    #     time.sleep(POLL_INTERVAL_SECONDS)
    #     job: ACPJob = acp_client.get_job_by_onchain_id(job_id)
    #     logger.info(f"Polling Job {job_id}: Phase={job.phase.name}")
    #
    #     if (
    #         job.phase == ACPJobPhase.NEGOTIATION
    #         and job.latest_memo.next_phase == ACPJobPhase.TRANSACTION
    #     ):
    #         logger.info(f"Paying job {job_id}")
    #         job.pay_and_accept_requirement()
    #     elif job.phase == ACPJobPhase.COMPLETED:
    #         logger.info(f"Job completed: {job}")
    #         break
    #     elif job.phase == ACPJobPhase.REJECTED:
    #         logger.info(f"Job rejected: {job}")
    #         break

    logger.info("--- Safe Buyer Script Finished ---")


if __name__ == "__main__":
    safe_buyer()
