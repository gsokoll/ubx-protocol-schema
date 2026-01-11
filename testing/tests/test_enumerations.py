"""Tests for enumeration definitions in enumerations.json."""

import pytest
import json
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.schema_loader import get_all_messages


# Type capacity limits
TYPE_MAX_VALUES = {
    "U1": 255,
    "U2": 65535,
    "U4": 4294967295,
    "U8": 18446744073709551615,
    "I1": 127,
    "I2": 32767,
    "I4": 2147483647,
    "I8": 9223372036854775807,
}

TYPE_MIN_VALUES = {
    "U1": 0,
    "U2": 0,
    "U4": 0,
    "U8": 0,
    "I1": -128,
    "I2": -32768,
    "I4": -2147483648,
    "I8": -9223372036854775808,
}


def load_enumerations():
    """Load enumerations from JSON file."""
    enums_path = Path(__file__).parent.parent.parent / "data" / "messages" / "enumerations.json"
    with open(enums_path) as f:
        return json.load(f)


def get_enum_names():
    """Get list of enumeration names for parametrization."""
    return list(load_enumerations().keys())


class TestEnumerationSchema:
    """Test enumeration schema integrity."""

    def test_all_enums_have_required_fields(self):
        """Every enumeration should have type and values fields (or per_gnss for special enums)."""
        enums = load_enumerations()

        for name, enum_def in enums.items():
            # per_gnss enums (like sigId) have different structure
            if "per_gnss" in enum_def:
                continue
            assert "type" in enum_def, f"Enumeration '{name}' missing 'type' field"
            assert "values" in enum_def, f"Enumeration '{name}' missing 'values' field"
            assert isinstance(enum_def["values"], list), f"Enumeration '{name}' values should be a list"

    def test_enum_types_are_valid(self):
        """Enumeration types should be valid UBX types."""
        enums = load_enumerations()
        valid_types = {"U1", "U2", "U4", "U8", "I1", "I2", "I4", "I8"}

        for name, enum_def in enums.items():
            enum_type = enum_def.get("type")
            # Handle per_gnss special case (sigId enum)
            if "per_gnss" in enum_def:
                continue
            assert enum_type in valid_types, f"Enumeration '{name}' has invalid type '{enum_type}'"

    @pytest.mark.parametrize("enum_name", get_enum_names())
    def test_enum_values_have_required_fields(self, enum_name):
        """Each enum value should have value and name fields."""
        enums = load_enumerations()
        enum_def = enums[enum_name]

        # Handle per_gnss special case
        if "per_gnss" in enum_def:
            for gnss_name, gnss_def in enum_def["per_gnss"].items():
                for signal in gnss_def.get("signals", []):
                    assert "value" in signal, f"Signal in '{enum_name}.{gnss_name}' missing 'value'"
                    assert "name" in signal, f"Signal in '{enum_name}.{gnss_name}' missing 'name'"
            return

        for val in enum_def.get("values", []):
            assert "value" in val, f"Value in '{enum_name}' missing 'value' field"
            assert "name" in val, f"Value in '{enum_name}' missing 'name' field"

    @pytest.mark.parametrize("enum_name", get_enum_names())
    def test_enum_values_fit_type(self, enum_name):
        """Enum values should fit within the type's capacity."""
        enums = load_enumerations()
        enum_def = enums[enum_name]

        # Handle per_gnss special case
        if "per_gnss" in enum_def:
            return  # Per-GNSS enums use U1 implicitly

        enum_type = enum_def.get("type")
        if enum_type not in TYPE_MAX_VALUES:
            pytest.skip(f"Unknown type '{enum_type}'")

        max_val = TYPE_MAX_VALUES[enum_type]
        min_val = TYPE_MIN_VALUES[enum_type]

        for val in enum_def.get("values", []):
            v = val["value"]
            assert min_val <= v <= max_val, (
                f"Value {v} in '{enum_name}' exceeds {enum_type} range [{min_val}, {max_val}]"
            )

    @pytest.mark.parametrize("enum_name", get_enum_names())
    def test_no_duplicate_values(self, enum_name):
        """Enum values should not have duplicates."""
        enums = load_enumerations()
        enum_def = enums[enum_name]

        # Handle per_gnss special case
        if "per_gnss" in enum_def:
            for gnss_name, gnss_def in enum_def["per_gnss"].items():
                values = [s["value"] for s in gnss_def.get("signals", [])]
                unique_values = set(values)
                assert len(values) == len(unique_values), (
                    f"Duplicate values in '{enum_name}.{gnss_name}'"
                )
            return

        values = [v["value"] for v in enum_def.get("values", [])]
        unique_values = set(values)
        assert len(values) == len(unique_values), f"Duplicate values in '{enum_name}'"

    @pytest.mark.parametrize("enum_name", get_enum_names())
    def test_no_duplicate_names(self, enum_name):
        """Enum value names should be unique within an enum."""
        enums = load_enumerations()
        enum_def = enums[enum_name]

        # Handle per_gnss special case
        if "per_gnss" in enum_def:
            return  # Names can repeat across GNSS systems

        names = [v["name"] for v in enum_def.get("values", [])]
        unique_names = set(names)
        assert len(names) == len(unique_names), f"Duplicate names in '{enum_name}'"


class TestEnumerationCrossReference:
    """Test enumeration cross-references with messages."""

    def test_occurrences_count_present(self):
        """Enumerations should have occurrence tracking."""
        enums = load_enumerations()

        for name, enum_def in enums.items():
            # Per-GNSS enums may not have occurrences
            if "per_gnss" in enum_def:
                continue
            assert "occurrences" in enum_def or "messages" in enum_def, (
                f"Enumeration '{name}' missing occurrence tracking"
            )

    def test_messages_list_exists(self):
        """Enumerations with occurrences should list messages."""
        enums = load_enumerations()

        for name, enum_def in enums.items():
            if "per_gnss" in enum_def:
                continue
            if enum_def.get("occurrences", 0) > 0:
                assert "messages" in enum_def, (
                    f"Enumeration '{name}' has occurrences but no messages list"
                )
                assert len(enum_def["messages"]) > 0, (
                    f"Enumeration '{name}' has empty messages list"
                )

    def test_referenced_messages_exist(self):
        """Messages referenced by enumerations should exist in schema."""
        enums = load_enumerations()
        message_names = {msg.get("name") for msg in get_all_messages()}

        missing = []
        for name, enum_def in enums.items():
            if "per_gnss" in enum_def:
                continue
            for msg_name in enum_def.get("messages", []):
                if msg_name not in message_names:
                    missing.append((name, msg_name))

        # Report all missing at once
        if missing:
            msg = "Messages referenced by enumerations but not in schema:\n"
            for enum_name, msg_name in missing[:10]:
                msg += f"  {enum_name} -> {msg_name}\n"
            if len(missing) > 10:
                msg += f"  ... and {len(missing) - 10} more"
            pytest.fail(msg)


class TestEnumerationContent:
    """Test enumeration content quality."""

    def test_total_enumeration_count(self):
        """Verify we have the expected number of enumerations."""
        enums = load_enumerations()
        # Currently have 23 enumerations
        assert len(enums) >= 20, f"Expected at least 20 enumerations, got {len(enums)}"

    def test_enum_values_have_descriptions(self):
        """Most enum values should have descriptions."""
        enums = load_enumerations()

        total_values = 0
        with_description = 0

        for name, enum_def in enums.items():
            if "per_gnss" in enum_def:
                continue
            for val in enum_def.get("values", []):
                total_values += 1
                if val.get("description"):
                    with_description += 1

        # At least 80% should have descriptions
        if total_values > 0:
            ratio = with_description / total_values
            assert ratio >= 0.8, (
                f"Only {ratio:.1%} of enum values have descriptions (expected >= 80%)"
            )

    def test_sigId_has_gnss_contexts(self):
        """The sigId enumeration should have per-GNSS contexts."""
        enums = load_enumerations()

        if "sigId" not in enums:
            pytest.skip("sigId enumeration not present")

        sig_id = enums["sigId"]
        assert "per_gnss" in sig_id, "sigId should have per_gnss structure"

        expected_gnss = {"gps", "galileo", "beidou", "glonass"}
        actual_gnss = set(sig_id["per_gnss"].keys())

        # Should have at least some common GNSS systems
        common = expected_gnss & actual_gnss
        assert len(common) >= 2, f"sigId should have multiple GNSS systems, found: {actual_gnss}"
