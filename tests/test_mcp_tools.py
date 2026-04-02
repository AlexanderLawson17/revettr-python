"""Tests for MCP server tools: is_safe_to_transact, score_batch, explain_risk, health_check.

Uses unittest.mock.AsyncMock to patch _score_one so tests run without
network access or fastmcp optional dependency issues.
"""

import asyncio
import math
import re
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


def _fastmcp_available() -> bool:
    try:
        import fastmcp  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(
    not _fastmcp_available(), reason="fastmcp not installed"
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

VALID_WALLET = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
VALID_WALLET_2 = "0x1234567890abcdef1234567890abcdef12345678"

MOCK_SCORE_RESPONSE = {
    "score": 85,
    "tier": "low",
    "confidence": 0.9,
    "signals_checked": 3,
    "flags": [],
}

MOCK_RISKY_RESPONSE = {
    "score": 25,
    "tier": "critical",
    "confidence": 0.8,
    "signals_checked": 4,
    "flags": ["sanctions_exact_match", "wallet_never_transacted"],
}

MOCK_MEDIUM_RESPONSE = {
    "score": 65,
    "tier": "medium",
    "confidence": 0.7,
    "signals_checked": 2,
    "flags": ["domain_age_under_30d", "no_mx_records"],
}

MOCK_HIGH_RESPONSE = {
    "score": 40,
    "tier": "high",
    "confidence": 0.6,
    "signals_checked": 3,
    "flags": ["wallet_age_under_7d", "low_counterparty_diversity"],
}


# ---------------------------------------------------------------------------
# score_counterparty — amount_usd parameter
# ---------------------------------------------------------------------------


class TestScoreCounterpartyAmountUsd:
    """Test the new amount_usd parameter on score_counterparty."""

    def test_amount_usd_added_to_body(self):
        from revettr_mcp.server import score_counterparty

        with patch("revettr_mcp.server._score_one", new_callable=AsyncMock) as mock:
            mock.return_value = MOCK_SCORE_RESPONSE
            result = asyncio.run(
                score_counterparty(wallet_address=VALID_WALLET, amount_usd=100.0)
            )
            call_body = mock.call_args[0][0]
            assert call_body["amount"] == 100.0

    def test_amount_usd_nan_rejected(self):
        from revettr_mcp.server import score_counterparty

        result = asyncio.run(
            score_counterparty(wallet_address=VALID_WALLET, amount_usd=float("nan"))
        )
        assert "error" in result
        assert "finite" in result["error"]

    def test_amount_usd_inf_rejected(self):
        from revettr_mcp.server import score_counterparty

        result = asyncio.run(
            score_counterparty(wallet_address=VALID_WALLET, amount_usd=float("inf"))
        )
        assert "error" in result
        assert "finite" in result["error"]

    def test_amount_usd_negative_rejected(self):
        from revettr_mcp.server import score_counterparty

        result = asyncio.run(
            score_counterparty(wallet_address=VALID_WALLET, amount_usd=-5.0)
        )
        assert "error" in result
        assert "greater than 0" in result["error"]

    def test_amount_usd_none_ok(self):
        from revettr_mcp.server import score_counterparty

        with patch("revettr_mcp.server._score_one", new_callable=AsyncMock) as mock:
            mock.return_value = MOCK_SCORE_RESPONSE
            result = asyncio.run(
                score_counterparty(wallet_address=VALID_WALLET, amount_usd=None)
            )
            call_body = mock.call_args[0][0]
            assert "amount" not in call_body


# ---------------------------------------------------------------------------
# is_safe_to_transact
# ---------------------------------------------------------------------------


class TestIsSafeToTransact:
    """Test the is_safe_to_transact tool."""

    def test_safe_wallet(self):
        from revettr_mcp.server import is_safe_to_transact

        with patch("revettr_mcp.server._score_one", new_callable=AsyncMock) as mock:
            mock.return_value = MOCK_SCORE_RESPONSE
            result = asyncio.run(is_safe_to_transact(wallet_address=VALID_WALLET))
            assert result["safe"] is True
            assert result["score"] == 85
            assert result["blocking_flags"] == []

    def test_unsafe_wallet(self):
        from revettr_mcp.server import is_safe_to_transact

        with patch("revettr_mcp.server._score_one", new_callable=AsyncMock) as mock:
            mock.return_value = MOCK_RISKY_RESPONSE
            result = asyncio.run(is_safe_to_transact(wallet_address=VALID_WALLET))
            assert result["safe"] is False
            assert result["score"] == 25
            assert len(result["blocking_flags"]) > 0

    def test_custom_min_score(self):
        from revettr_mcp.server import is_safe_to_transact

        with patch("revettr_mcp.server._score_one", new_callable=AsyncMock) as mock:
            mock.return_value = MOCK_MEDIUM_RESPONSE  # score=65
            result = asyncio.run(
                is_safe_to_transact(wallet_address=VALID_WALLET, min_score=70)
            )
            assert result["safe"] is False

    def test_invalid_wallet_rejected(self):
        from revettr_mcp.server import is_safe_to_transact

        result = asyncio.run(is_safe_to_transact(wallet_address="not-a-wallet"))
        assert "error" in result
        assert "Invalid EVM" in result["error"]

    def test_min_score_out_of_range(self):
        from revettr_mcp.server import is_safe_to_transact

        result = asyncio.run(
            is_safe_to_transact(wallet_address=VALID_WALLET, min_score=150)
        )
        assert "error" in result
        assert "between 0 and 100" in result["error"]

    def test_min_score_negative(self):
        from revettr_mcp.server import is_safe_to_transact

        result = asyncio.run(
            is_safe_to_transact(wallet_address=VALID_WALLET, min_score=-1)
        )
        assert "error" in result

    def test_amount_usd_passed_through(self):
        from revettr_mcp.server import is_safe_to_transact

        with patch("revettr_mcp.server._score_one", new_callable=AsyncMock) as mock:
            mock.return_value = MOCK_SCORE_RESPONSE
            asyncio.run(
                is_safe_to_transact(wallet_address=VALID_WALLET, amount_usd=50.0)
            )
            call_body = mock.call_args[0][0]
            assert call_body["amount"] == 50.0

    def test_api_error_passed_through(self):
        from revettr_mcp.server import is_safe_to_transact

        with patch("revettr_mcp.server._score_one", new_callable=AsyncMock) as mock:
            mock.return_value = {"error": "API returned status 500"}
            result = asyncio.run(is_safe_to_transact(wallet_address=VALID_WALLET))
            assert "error" in result


# ---------------------------------------------------------------------------
# score_batch
# ---------------------------------------------------------------------------


class TestScoreBatch:
    """Test the score_batch tool."""

    def test_batch_two_wallets(self):
        from revettr_mcp.server import score_batch

        responses = [
            {"score": 90, "tier": "low", "flags": []},
            {"score": 40, "tier": "high", "flags": ["wallet_age_under_7d"]},
        ]

        with patch("revettr_mcp.server._score_one", new_callable=AsyncMock) as mock:
            mock.side_effect = responses
            result = asyncio.run(score_batch(wallets=[
                {"wallet_address": VALID_WALLET},
                {"wallet_address": VALID_WALLET_2},
            ]))
            assert result["total_scored"] == 2
            assert len(result["results"]) == 2
            # Sorted descending by score
            assert result["results"][0]["score"] >= result["results"][1]["score"]

    def test_empty_wallets_rejected(self):
        from revettr_mcp.server import score_batch

        result = asyncio.run(score_batch(wallets=[]))
        assert "error" in result
        assert "at least 1" in result["error"]

    def test_too_many_wallets_rejected(self):
        from revettr_mcp.server import score_batch

        wallets = [{"wallet_address": VALID_WALLET}] * 11
        result = asyncio.run(score_batch(wallets=wallets))
        assert "error" in result
        assert "at most 10" in result["error"]

    def test_invalid_wallet_in_batch(self):
        from revettr_mcp.server import score_batch

        result = asyncio.run(score_batch(wallets=[
            {"wallet_address": "bad-address"},
        ]))
        assert "error" in result

    def test_missing_wallet_address_key(self):
        from revettr_mcp.server import score_batch

        result = asyncio.run(score_batch(wallets=[
            {"chain": "base"},
        ]))
        assert "error" in result
        assert "missing wallet_address" in result["error"]

    def test_partial_failure(self):
        """When some wallets score and others error, both buckets are populated."""
        from revettr_mcp.server import score_batch

        with patch("revettr_mcp.server._score_one", new_callable=AsyncMock) as mock:
            mock.side_effect = [
                {"score": 90, "tier": "low", "flags": []},
                {"error": "API returned status 500"},
                {"score": 60, "tier": "medium", "flags": ["wallet_age_under_30d"]},
            ]
            result = asyncio.run(score_batch(wallets=[
                {"wallet_address": VALID_WALLET},
                {"wallet_address": VALID_WALLET_2},
                {"wallet_address": f"0x{'b' * 40}"},
            ]))
            assert result["total_scored"] == 2
            assert len(result["results"]) == 2
            assert len(result["errors"]) == 1
            assert result["errors"][0]["wallet_address"] == VALID_WALLET_2
            # Results still sorted by score descending
            assert result["results"][0]["score"] >= result["results"][1]["score"]

    def test_max_results_truncation(self):
        from revettr_mcp.server import score_batch

        responses = [
            {"score": 90 - i * 10, "tier": "low", "flags": []}
            for i in range(3)
        ]

        with patch("revettr_mcp.server._score_one", new_callable=AsyncMock) as mock:
            mock.side_effect = responses
            result = asyncio.run(score_batch(
                wallets=[
                    {"wallet_address": f"0x{'a' * 38}{i:02d}"} for i in range(3)
                ],
                max_results=2,
            ))
            assert len(result["results"]) == 2


# ---------------------------------------------------------------------------
# explain_risk
# ---------------------------------------------------------------------------


class TestExplainRisk:
    """Test the explain_risk tool."""

    def test_explain_with_known_flags(self):
        from revettr_mcp.server import explain_risk

        with patch("revettr_mcp.server._score_one", new_callable=AsyncMock) as mock:
            mock.return_value = MOCK_MEDIUM_RESPONSE
            result = asyncio.run(explain_risk(domain="example.com"))
            assert result["score"] == 65
            assert result["tier"] == "medium"
            assert result["recommendation"] == "Proceed with caution."
            assert len(result["risk_factors"]) == 2
            # Check that descriptions are filled in
            for rf in result["risk_factors"]:
                assert "description" in rf
                assert len(rf["description"]) > 10

    def test_explain_critical_tier(self):
        from revettr_mcp.server import explain_risk

        with patch("revettr_mcp.server._score_one", new_callable=AsyncMock) as mock:
            mock.return_value = MOCK_RISKY_RESPONSE
            result = asyncio.run(explain_risk(wallet_address=VALID_WALLET))
            assert result["recommendation"] == "Do not transact."
            assert result["tier"] == "critical"

    def test_explain_no_identifiers_rejected(self):
        from revettr_mcp.server import explain_risk

        result = asyncio.run(explain_risk())
        assert "error" in result
        assert "At least one" in result["error"]

    def test_explain_unknown_flag(self):
        from revettr_mcp.server import explain_risk

        with patch("revettr_mcp.server._score_one", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "score": 50, "tier": "high", "flags": ["some_unknown_flag"],
                "confidence": 0.5, "signals_checked": 1,
            }
            result = asyncio.run(explain_risk(domain="example.com"))
            rf = result["risk_factors"][0]
            assert "some unknown flag" in rf["description"]

    def test_explain_high_risk_country_flag(self):
        from revettr_mcp.server import explain_risk

        with patch("revettr_mcp.server._score_one", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "score": 30, "tier": "high", "flags": ["high_risk_country_north_korea"],
                "confidence": 0.9, "signals_checked": 1,
            }
            result = asyncio.run(explain_risk(domain="example.com"))
            rf = result["risk_factors"][0]
            assert "North Korea" in rf["description"]

    def test_explain_low_tier_recommendation(self):
        from revettr_mcp.server import explain_risk

        with patch("revettr_mcp.server._score_one", new_callable=AsyncMock) as mock:
            mock.return_value = MOCK_SCORE_RESPONSE  # tier="low"
            result = asyncio.run(explain_risk(wallet_address=VALID_WALLET))
            assert result["recommendation"] == "Safe to proceed."

    def test_explain_summary_no_flags(self):
        from revettr_mcp.server import explain_risk

        with patch("revettr_mcp.server._score_one", new_callable=AsyncMock) as mock:
            mock.return_value = MOCK_SCORE_RESPONSE  # flags=[]
            result = asyncio.run(explain_risk(wallet_address=VALID_WALLET))
            assert "No specific risk flags" in result["summary"]


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """Test the health_check tool."""

    def test_health_check_success(self):
        from revettr_mcp.server import health_check

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok", "version": "0.4.0"}

        with patch("httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.get.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = asyncio.run(health_check())
            assert result["status"] == "ok"

    def test_health_check_server_error(self):
        from revettr_mcp.server import health_check

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.get.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = asyncio.run(health_check())
            assert "error" in result
            assert "500" in result["error"]

    def test_health_check_timeout(self):
        from revettr_mcp.server import health_check

        with patch("httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.get.side_effect = httpx.TimeoutException("timed out")
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = asyncio.run(health_check())
            assert "error" in result
            assert "timed out" in result["error"].lower()


# ---------------------------------------------------------------------------
# _score_one routing
# ---------------------------------------------------------------------------


class TestScoreOneRouting:
    """Test that _score_one correctly routes to x402 or direct."""

    def test_score_one_without_wallet_key(self):
        from revettr_mcp.server import _score_one

        with patch.dict("os.environ", {}, clear=True):
            with patch("revettr_mcp.server._call_direct", new_callable=AsyncMock) as mock_direct:
                mock_direct.return_value = MOCK_SCORE_RESPONSE
                result = asyncio.run(_score_one({"wallet_address": VALID_WALLET}))
                mock_direct.assert_called_once()
                assert result["score"] == 85

    def test_score_one_with_wallet_key(self):
        from revettr_mcp.server import _score_one

        with patch.dict("os.environ", {"REVETTR_WALLET_KEY": "0xfakekey"}):
            with patch("revettr_mcp.server._call_with_x402_payment", new_callable=AsyncMock) as mock_x402:
                mock_x402.return_value = MOCK_SCORE_RESPONSE
                result = asyncio.run(_score_one({"wallet_address": VALID_WALLET}))
                mock_x402.assert_called_once()
                assert result["score"] == 85
