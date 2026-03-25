"""Tests for the Revettr client SDK."""
import ipaddress
import math
import pytest
from revettr.client import Revettr, RevettrPaymentRequired
from revettr.models import ScoreResponse, SignalScore


class TestInputValidation:
    """Test _validate_inputs defense-in-depth validation."""

    def test_valid_domain(self):
        Revettr._validate_inputs("example.com", None, None, "base", None, None, None)

    def test_valid_url_domain(self):
        # URL with long path should pass (hostname is short)
        Revettr._validate_inputs("https://example.com/" + "a" * 300, None, None, "base", None, None, None)

    def test_domain_too_long(self):
        with pytest.raises(ValueError, match="253"):
            Revettr._validate_inputs("a" * 254, None, None, "base", None, None, None)

    def test_domain_whitespace(self):
        with pytest.raises(ValueError, match="whitespace"):
            Revettr._validate_inputs("exam ple.com", None, None, "base", None, None, None)

    def test_valid_ip(self):
        Revettr._validate_inputs(None, "104.18.28.72", None, "base", None, None, None)

    def test_invalid_ip(self):
        with pytest.raises(ValueError, match="Invalid IP"):
            Revettr._validate_inputs(None, "999.999.999.999", None, "base", None, None, None)

    def test_valid_wallet(self):
        Revettr._validate_inputs(None, None, "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "base", None, None, None)

    def test_invalid_wallet_short(self):
        with pytest.raises(ValueError, match="Invalid EVM"):
            Revettr._validate_inputs(None, None, "0xabc", "base", None, None, None)

    def test_invalid_wallet_no_prefix(self):
        with pytest.raises(ValueError, match="Invalid EVM"):
            Revettr._validate_inputs(None, None, "d8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "base", None, None, None)

    def test_company_name_too_long(self):
        with pytest.raises(ValueError, match="200"):
            Revettr._validate_inputs(None, None, None, "base", "x" * 201, None, None)

    def test_amount_negative(self):
        with pytest.raises(ValueError, match="greater than 0"):
            Revettr._validate_inputs(None, None, None, "base", None, None, -1.0)

    def test_amount_nan(self):
        with pytest.raises(ValueError, match="finite"):
            Revettr._validate_inputs(None, None, None, "base", None, None, float("nan"))

    def test_amount_inf(self):
        with pytest.raises(ValueError, match="finite"):
            Revettr._validate_inputs(None, None, None, "base", None, None, float("inf"))

    def test_amount_huge_int(self):
        with pytest.raises(ValueError, match="too large"):
            Revettr._validate_inputs(None, None, None, "base", None, None, 10**1000)

    def test_valid_email(self):
        Revettr._validate_inputs(None, None, None, "base", None, "test@example.com", None)

    def test_invalid_email_no_at(self):
        with pytest.raises(ValueError, match="Invalid email"):
            Revettr._validate_inputs(None, None, None, "base", None, "notanemail", None)

    def test_chain_empty(self):
        with pytest.raises(ValueError, match="non-empty"):
            Revettr._validate_inputs(None, None, None, "   ", None, None, None)

    def test_no_inputs_raises(self):
        """score() with no inputs should raise ValueError."""
        client = Revettr()
        with pytest.raises(ValueError, match="At least one"):
            client.score()


class TestBaseUrlValidation:
    """Test HTTPS enforcement."""

    def test_https_allowed(self):
        client = Revettr(base_url="https://revettr.com")
        assert client.base_url == "https://revettr.com"

    def test_localhost_http_allowed(self):
        client = Revettr(base_url="http://localhost:4021")
        assert client.base_url == "http://localhost:4021"

    def test_http_blocked(self):
        with pytest.raises(ValueError, match="HTTPS"):
            Revettr(base_url="http://evil.com")


class TestModels:
    """Test ScoreResponse and SignalScore."""

    def test_score_response_from_dict(self):
        data = {
            "score": 85,
            "tier": "low",
            "confidence": 0.75,
            "signals_checked": 3,
            "flags": ["no_dmarc_record"],
            "signal_scores": {
                "domain": {"score": 90, "flags": ["no_dmarc_record"], "available": True, "details": {}}
            },
            "metadata": {"version": "0.1.0"},
        }
        resp = ScoreResponse.from_dict(data)
        assert resp.score == 85
        assert resp.tier == "low"
        assert resp.confidence == 0.75
        assert resp.flags == ["no_dmarc_record"]
        assert "domain" in resp.signal_scores

    def test_signal_score_defaults(self):
        s = SignalScore(score=50)
        assert s.flags == []
        assert s.available is True
        assert s.details == {}


class TestClientInit:
    """Test client initialization."""

    def test_default_url(self):
        client = Revettr()
        assert client.base_url == "https://revettr.com"

    def test_repr_no_secrets(self):
        client = Revettr()
        r = repr(client)
        assert "revettr.com" in r
        assert "x402=disabled" in r
        # Should not contain any private key info
        assert "0x" not in r
