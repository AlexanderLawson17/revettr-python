"""Tests for FLAG_DESCRIPTIONS completeness, formatting, and correctness."""

import pathlib
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

# Expected flag keys that must be present
EXPECTED_FLAGS = [
    "domain_age_under_30d",
    "domain_age_under_90d",
    "no_mx_records",
    "ssl_invalid",
    "ssl_missing",
    "tor_exit_node",
    "known_vpn",
    "datacenter_ip",
    "wallet_never_transacted",
    "wallet_age_under_7d",
    "wallet_age_under_30d",
    "wallet_age_under_90d",
    "low_counterparty_diversity",
    "sanctions_exact_match",
    "sanctions_high_confidence_match",
    "no_spf_record",
    "no_dmarc_record",
]


class TestFlagDescriptionsCompleteness:
    """Ensure FLAG_DESCRIPTIONS contains all expected flags."""

    def test_all_expected_flags_present(self):
        from revettr_mcp.server import FLAG_DESCRIPTIONS

        for flag in EXPECTED_FLAGS:
            assert flag in FLAG_DESCRIPTIONS, f"Missing flag: {flag}"

    def test_no_extra_unexpected_flags(self):
        """FLAG_DESCRIPTIONS should only contain known flags."""
        from revettr_mcp.server import FLAG_DESCRIPTIONS

        extra = set(FLAG_DESCRIPTIONS.keys()) - set(EXPECTED_FLAGS)
        assert extra == set(), f"Unexpected flags in FLAG_DESCRIPTIONS: {extra}"

    def test_flag_count_matches(self):
        from revettr_mcp.server import FLAG_DESCRIPTIONS

        assert len(FLAG_DESCRIPTIONS) == len(EXPECTED_FLAGS)


class TestFlagDescriptionsFormatting:
    """Ensure all flag descriptions are well-formed strings."""

    def test_all_descriptions_are_strings(self):
        from revettr_mcp.server import FLAG_DESCRIPTIONS

        for flag, desc in FLAG_DESCRIPTIONS.items():
            assert isinstance(desc, str), f"{flag}: description is not a string"

    def test_all_descriptions_nonempty(self):
        from revettr_mcp.server import FLAG_DESCRIPTIONS

        for flag, desc in FLAG_DESCRIPTIONS.items():
            assert len(desc.strip()) > 0, f"{flag}: description is empty"

    def test_all_descriptions_end_with_period(self):
        from revettr_mcp.server import FLAG_DESCRIPTIONS

        for flag, desc in FLAG_DESCRIPTIONS.items():
            assert desc.strip().endswith("."), (
                f"{flag}: description does not end with a period: {desc!r}"
            )

    def test_descriptions_are_human_readable_length(self):
        """Descriptions should be between 10 and 500 characters."""
        from revettr_mcp.server import FLAG_DESCRIPTIONS

        for flag, desc in FLAG_DESCRIPTIONS.items():
            assert 10 <= len(desc) <= 500, (
                f"{flag}: description length {len(desc)} outside expected range"
            )

    def test_sanctions_flags_are_emphatic(self):
        """Sanctions flags should contain strong language."""
        from revettr_mcp.server import FLAG_DESCRIPTIONS

        exact = FLAG_DESCRIPTIONS["sanctions_exact_match"]
        assert "CRITICAL" in exact or "Do not" in exact, (
            "sanctions_exact_match should contain urgent language"
        )

        high = FLAG_DESCRIPTIONS["sanctions_high_confidence_match"]
        assert "sanctions" in high.lower(), (
            "sanctions_high_confidence_match should mention sanctions"
        )


class TestFlagDescriptionsContent:
    """Spot-check specific flag descriptions for correctness."""

    def test_domain_age_30d_mentions_30_days(self):
        from revettr_mcp.server import FLAG_DESCRIPTIONS

        assert "30 days" in FLAG_DESCRIPTIONS["domain_age_under_30d"]

    def test_tor_flag_mentions_tor(self):
        from revettr_mcp.server import FLAG_DESCRIPTIONS

        assert "Tor" in FLAG_DESCRIPTIONS["tor_exit_node"]

    def test_ssl_missing_mentions_ssl(self):
        from revettr_mcp.server import FLAG_DESCRIPTIONS

        assert "SSL" in FLAG_DESCRIPTIONS["ssl_missing"] or "ssl" in FLAG_DESCRIPTIONS["ssl_missing"]

    def test_wallet_never_transacted_mentions_on_chain(self):
        from revettr_mcp.server import FLAG_DESCRIPTIONS

        assert "on-chain" in FLAG_DESCRIPTIONS["wallet_never_transacted"]

    def test_spf_flag_mentions_spf(self):
        from revettr_mcp.server import FLAG_DESCRIPTIONS

        assert "SPF" in FLAG_DESCRIPTIONS["no_spf_record"]

    def test_dmarc_flag_mentions_dmarc(self):
        from revettr_mcp.server import FLAG_DESCRIPTIONS

        assert "DMARC" in FLAG_DESCRIPTIONS["no_dmarc_record"]
