"""Test variant message handling."""

import pytest
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.schema_loader import (
    get_message_by_name,
    get_variant_by_alias,
    select_variant_by_payload,
)
from lib.ubx_generator import generate_ubx_message, generate_test_values
from lib.ubx_parser import parse_ubx_message


class TestVariantLookup:
    """Test variant lookup functions."""

    def test_get_message_by_name_finds_consolidated(self):
        """Base message name finds consolidated message."""
        msg = get_message_by_name("UBX-MGA-GPS")
        assert msg is not None
        assert msg["name"] == "UBX-MGA-GPS"
        assert "variants" in msg
        assert len(msg["variants"]) == 5

    def test_get_message_by_name_finds_by_alias(self):
        """Legacy suffix name finds parent message via alias."""
        msg = get_message_by_name("UBX-MGA-GPS-EPH")
        assert msg is not None
        assert msg["name"] == "UBX-MGA-GPS"  # Returns parent, not variant

    def test_get_variant_by_alias_returns_parent_and_variant(self):
        """get_variant_by_alias returns both parent message and variant."""
        result = get_variant_by_alias("UBX-MGA-GPS-EPH")
        assert result is not None
        parent, variant = result
        assert parent["name"] == "UBX-MGA-GPS"
        assert variant["name"] == "EPH"
        assert variant["discriminator"]["value"] == 1

    def test_get_variant_by_alias_returns_none_for_non_alias(self):
        """get_variant_by_alias returns None for non-alias names."""
        result = get_variant_by_alias("UBX-NAV-PVT")  # Not an alias
        assert result is None


class TestVariantSelection:
    """Test variant selection from payload."""

    def test_select_variant_by_type_field(self):
        """Correct variant is selected based on type field value."""
        msg = get_message_by_name("UBX-MGA-GPS")

        # EPH has type=1
        payload_eph = bytes([1] + [0] * 67)
        variant = select_variant_by_payload(msg, payload_eph)
        assert variant is not None
        assert variant["name"] == "EPH"

        # ALM has type=2
        payload_alm = bytes([2] + [0] * 35)
        variant = select_variant_by_payload(msg, payload_alm)
        assert variant is not None
        assert variant["name"] == "ALM"

        # HEALTH has type=4
        payload_health = bytes([4] + [0] * 39)
        variant = select_variant_by_payload(msg, payload_health)
        assert variant is not None
        assert variant["name"] == "HEALTH"

    def test_select_variant_returns_none_for_unknown_type(self):
        """Returns None when no variant matches."""
        msg = get_message_by_name("UBX-MGA-GPS")
        # Type 99 doesn't exist
        payload_unknown = bytes([99] + [0] * 35)
        variant = select_variant_by_payload(msg, payload_unknown)
        assert variant is None


class TestVariantGeneration:
    """Test generating variant messages."""

    def test_generate_test_values_includes_discriminator(self):
        """Generated values include the discriminator field."""
        msg = get_message_by_name("UBX-MGA-GPS")
        values = generate_test_values(msg, variant_name="EPH")
        assert values.get("type") == 1

        values = generate_test_values(msg, variant_name="ALM")
        assert values.get("type") == 2

    def test_generate_variant_message_has_correct_type(self):
        """Generated variant message has correct type field in payload."""
        msg = get_message_by_name("UBX-MGA-GPS")

        # Generate EPH variant
        binary = generate_ubx_message(msg, variant_name="EPH")
        # Type field is at payload offset 0, which is byte 6 in full message
        assert binary[6] == 1

        # Generate ALM variant
        binary = generate_ubx_message(msg, variant_name="ALM")
        assert binary[6] == 2


class TestVariantParsing:
    """Test parsing variant messages."""

    def test_parse_identifies_correct_variant(self):
        """Parser correctly identifies variant from payload."""
        msg = get_message_by_name("UBX-MGA-GPS")

        # Generate and parse EPH variant
        binary = generate_ubx_message(msg, variant_name="EPH")
        parsed = parse_ubx_message(binary, msg)

        assert parsed["parsed"] is True
        assert parsed["variant"] == "EPH"
        assert parsed["variant_alias"] == "UBX-MGA-GPS-EPH"
        assert parsed["fields"]["type"] == 1

    def test_parse_variant_roundtrip(self):
        """Variant message round-trips correctly."""
        msg = get_message_by_name("UBX-MGA-GPS")

        for variant_name in ["EPH", "ALM", "HEALTH", "UTC", "IONO"]:
            values = generate_test_values(msg, variant_name=variant_name)
            binary = generate_ubx_message(msg, field_values=values, variant_name=variant_name)
            parsed = parse_ubx_message(binary, msg)

            assert parsed["parsed"] is True, f"Failed to parse {variant_name}"
            assert parsed["variant"] == variant_name, f"Wrong variant for {variant_name}"

            # Check type field matches
            variant_info = next(v for v in msg["variants"] if v["name"] == variant_name)
            expected_type = variant_info["discriminator"]["value"]
            assert parsed["fields"]["type"] == expected_type


class TestVariantAliasesProperty:
    """Test variant_aliases property in consolidated messages."""

    def test_variant_aliases_contains_legacy_names(self):
        """variant_aliases contains all legacy suffix names."""
        msg = get_message_by_name("UBX-MGA-GPS")
        aliases = msg.get("variant_aliases", [])

        expected = [
            "UBX-MGA-GPS-EPH",
            "UBX-MGA-GPS-ALM",
            "UBX-MGA-GPS-HEALTH",
            "UBX-MGA-GPS-UTC",
            "UBX-MGA-GPS-IONO",
        ]
        for name in expected:
            assert name in aliases, f"Missing alias: {name}"
