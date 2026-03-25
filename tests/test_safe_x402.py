"""Tests for SafeX402Client (import-only, since x402 deps are optional)."""
import pytest


def test_safe_x402_importable():
    """SafeX402Client should be importable when x402 deps are available."""
    try:
        from revettr.safe_x402 import SafeX402Client, PaymentBlocked
        assert SafeX402Client is not None
        assert PaymentBlocked is not None
    except ImportError:
        pytest.skip("x402 dependencies not installed")


def test_payment_blocked_exception():
    """PaymentBlocked should carry score, tier, and flags."""
    try:
        from revettr.safe_x402 import PaymentBlocked
    except ImportError:
        pytest.skip("x402 dependencies not installed")

    exc = PaymentBlocked("https://evil.com", score=15, tier="critical", flags=["sanctions_exact_match"])
    assert exc.score == 15
    assert exc.tier == "critical"
    assert exc.url == "https://evil.com"
    assert "sanctions_exact_match" in exc.flags
    assert "15/100" in str(exc)


def test_safe_x402_min_score_validation():
    """min_score must be 0-100."""
    try:
        from revettr.safe_x402 import SafeX402Client
    except ImportError:
        pytest.skip("x402 dependencies not installed")

    with pytest.raises(ValueError, match="0-100"):
        SafeX402Client(wallet_private_key="0x" + "a" * 64, min_score=150)


def test_safe_x402_on_fail_validation():
    """on_fail must be block/warn/log."""
    try:
        from revettr.safe_x402 import SafeX402Client
    except ImportError:
        pytest.skip("x402 dependencies not installed")

    with pytest.raises(ValueError, match="on_fail"):
        SafeX402Client(wallet_private_key="0x" + "a" * 64, on_fail="crash")
