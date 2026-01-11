"""Tests for configuration key definitions in unified_config_keys.json."""

import pytest
import json
import re
from pathlib import Path


# Valid data types for config keys
VALID_DATA_TYPES = {
    "L",  # Logical/boolean
    "U1", "U2", "U4", "U8",  # Unsigned integers
    "I1", "I2", "I4", "I8",  # Signed integers
    "E1", "E2", "E4", "E8",  # Enumerations
    "R4", "R8",  # Floats
    "X1", "X2", "X4", "X8",  # Bitfields
}

# Type capacity limits for enumeration types
ENUM_TYPE_MAX = {
    "E1": 255,
    "E2": 65535,
    "E4": 4294967295,
    "E8": 18446744073709551615,
}


def load_config_keys():
    """Load config keys from JSON file."""
    keys_path = Path(__file__).parent.parent.parent / "data" / "config_keys" / "unified_config_keys.json"
    with open(keys_path) as f:
        return json.load(f)


def get_all_keys():
    """Get list of all config keys."""
    data = load_config_keys()
    return data.get("keys", [])


def get_all_groups():
    """Get dict of all groups."""
    data = load_config_keys()
    return data.get("groups", {})


def get_keys_with_inline_enum():
    """Get config keys that have inline enumerations."""
    return [k for k in get_all_keys() if "inline_enum" in k]


class TestConfigKeySchema:
    """Test config key schema integrity."""

    def test_all_keys_have_required_fields(self):
        """Every config key should have required fields."""
        keys = get_all_keys()

        missing = []
        required = {"name", "key_id", "data_type", "group"}

        for key in keys:
            for field in required:
                if field not in key:
                    missing.append((key.get("name", "UNNAMED"), field))

        if missing:
            msg = "Config keys missing required fields:\n"
            for key_name, field in missing[:10]:
                msg += f"  {key_name} missing '{field}'\n"
            if len(missing) > 10:
                msg += f"  ... and {len(missing) - 10} more"
            pytest.fail(msg)

    def test_key_ids_valid_hex(self):
        """All key_id values should be valid hex format."""
        keys = get_all_keys()
        hex_pattern = re.compile(r"^0x[0-9a-fA-F]{8}$")

        invalid = []
        for key in keys:
            key_id = key.get("key_id", "")
            if not hex_pattern.match(key_id):
                invalid.append((key.get("name"), key_id))

        if invalid:
            msg = "Config keys with invalid key_id format:\n"
            for name, kid in invalid[:10]:
                msg += f"  {name}: '{kid}'\n"
            if len(invalid) > 10:
                msg += f"  ... and {len(invalid) - 10} more"
            pytest.fail(msg)

    def test_item_ids_valid_hex(self):
        """All item_id values should be valid hex format."""
        keys = get_all_keys()
        hex_pattern = re.compile(r"^0x[0-9a-fA-F]{4}$")

        invalid = []
        for key in keys:
            item_id = key.get("item_id")
            if item_id and not hex_pattern.match(item_id):
                invalid.append((key.get("name"), item_id))

        if invalid:
            msg = "Config keys with invalid item_id format:\n"
            for name, iid in invalid[:10]:
                msg += f"  {name}: '{iid}'\n"
            if len(invalid) > 10:
                msg += f"  ... and {len(invalid) - 10} more"
            pytest.fail(msg)

    def test_data_types_valid(self):
        """All data types should be valid UBX config types."""
        keys = get_all_keys()

        invalid = []
        for key in keys:
            data_type = key.get("data_type", "")
            # Handle array types like CH[n]
            base_type = data_type.split("[")[0] if "[" in data_type else data_type
            if base_type not in VALID_DATA_TYPES and base_type != "CH":
                invalid.append((key.get("name"), data_type))

        if invalid:
            msg = "Config keys with invalid data types:\n"
            for name, dtype in invalid[:10]:
                msg += f"  {name}: '{dtype}'\n"
            if len(invalid) > 10:
                msg += f"  ... and {len(invalid) - 10} more"
            pytest.fail(msg)

    def test_groups_exist(self):
        """All referenced groups should exist in groups section."""
        keys = get_all_keys()
        groups = get_all_groups()

        missing = []
        for key in keys:
            group = key.get("group")
            if group and group not in groups:
                missing.append((key.get("name"), group))

        if missing:
            msg = "Config keys referencing non-existent groups:\n"
            for name, group in missing[:10]:
                msg += f"  {name} -> '{group}'\n"
            if len(missing) > 10:
                msg += f"  ... and {len(missing) - 10} more"
            pytest.fail(msg)


class TestConfigKeyGroups:
    """Test config key group definitions."""

    def test_groups_have_required_fields(self):
        """All groups should have name and group_id."""
        groups = get_all_groups()

        for group_key, group in groups.items():
            assert "name" in group, f"Group '{group_key}' missing 'name'"
            assert "group_id" in group, f"Group '{group_key}' missing 'group_id'"

    def test_group_ids_valid_hex(self):
        """All group_id values should be valid hex format."""
        groups = get_all_groups()
        hex_pattern = re.compile(r"^0x[0-9a-fA-F]{2}$")

        invalid = []
        for group_key, group in groups.items():
            gid = group.get("group_id", "")
            if not hex_pattern.match(gid):
                invalid.append((group_key, gid))

        if invalid:
            msg = "Groups with invalid group_id format:\n"
            for name, gid in invalid:
                msg += f"  {name}: '{gid}'\n"
            pytest.fail(msg)

    def test_group_ids_unique(self):
        """All group_id values should be unique."""
        groups = get_all_groups()

        seen = {}
        duplicates = []
        for group_key, group in groups.items():
            gid = group.get("group_id")
            if gid in seen:
                duplicates.append((group_key, seen[gid], gid))
            else:
                seen[gid] = group_key

        if duplicates:
            msg = "Duplicate group_id values:\n"
            for g1, g2, gid in duplicates:
                msg += f"  {gid}: '{g1}' and '{g2}'\n"
            pytest.fail(msg)


class TestConfigKeyEnumerations:
    """Test inline enumeration definitions in config keys."""

    def test_inline_enum_count(self):
        """Verify we have inline enumerations."""
        keys_with_enum = get_keys_with_inline_enum()
        # Should have around 57 keys with inline_enum
        assert len(keys_with_enum) >= 50, (
            f"Expected at least 50 keys with inline_enum, got {len(keys_with_enum)}"
        )

    def test_inline_enum_has_values(self):
        """All inline enums should have values dict."""
        keys_with_enum = get_keys_with_inline_enum()

        for key in keys_with_enum:
            enum = key.get("inline_enum", {})
            assert "values" in enum, (
                f"Config key '{key.get('name')}' inline_enum missing 'values'"
            )
            assert isinstance(enum["values"], dict), (
                f"Config key '{key.get('name')}' inline_enum values should be dict"
            )

    def test_inline_enum_values_have_required_fields(self):
        """Each enum value should have value field."""
        keys_with_enum = get_keys_with_inline_enum()

        for key in keys_with_enum:
            enum = key.get("inline_enum", {})
            for val_name, val_def in enum.get("values", {}).items():
                assert "value" in val_def, (
                    f"Config key '{key.get('name')}' enum value '{val_name}' missing 'value'"
                )

    def test_inline_enum_values_fit_type(self):
        """Enum values should fit within the E-type capacity."""
        keys_with_enum = get_keys_with_inline_enum()

        for key in keys_with_enum:
            data_type = key.get("data_type", "")
            if data_type not in ENUM_TYPE_MAX:
                continue

            max_val = ENUM_TYPE_MAX[data_type]
            enum = key.get("inline_enum", {})

            for val_name, val_def in enum.get("values", {}).items():
                v = val_def.get("value", 0)
                # Handle hex string values
                if isinstance(v, str):
                    try:
                        v = int(v, 16) if v.startswith("0x") else int(v)
                    except ValueError:
                        continue  # Skip non-numeric values
                assert 0 <= v <= max_val, (
                    f"Config key '{key.get('name')}' enum value '{val_name}' ({v}) "
                    f"exceeds {data_type} max ({max_val})"
                )

    def test_inline_enum_no_duplicate_values(self):
        """Enum values should not have duplicates within a key."""
        keys_with_enum = get_keys_with_inline_enum()

        for key in keys_with_enum:
            enum = key.get("inline_enum", {})
            values = [v["value"] for v in enum.get("values", {}).values()]
            unique_values = set(values)

            if len(values) != len(unique_values):
                pytest.fail(
                    f"Config key '{key.get('name')}' has duplicate enum values"
                )


class TestConfigKeyContent:
    """Test config key content quality."""

    def test_total_key_count(self):
        """Verify we have the expected number of config keys."""
        keys = get_all_keys()
        # Currently have 1109 keys
        assert len(keys) >= 1000, f"Expected at least 1000 config keys, got {len(keys)}"

    def test_total_group_count(self):
        """Verify we have the expected number of groups."""
        groups = get_all_groups()
        # Should have around 47 groups
        assert len(groups) >= 40, f"Expected at least 40 groups, got {len(groups)}"

    def test_keys_have_descriptions(self):
        """Most config keys should have descriptions."""
        keys = get_all_keys()

        with_description = sum(1 for k in keys if k.get("description"))

        # At least 90% should have descriptions
        ratio = with_description / len(keys) if keys else 0
        assert ratio >= 0.9, (
            f"Only {ratio:.1%} of config keys have descriptions (expected >= 90%)"
        )

    def test_key_names_follow_convention(self):
        """Key names should follow CFG-GROUP-NAME convention."""
        keys = get_all_keys()
        pattern = re.compile(r"^CFG-[A-Z0-9]+-[A-Z0-9_]+$")

        non_matching = []
        for key in keys:
            name = key.get("name", "")
            if not pattern.match(name):
                non_matching.append(name)

        # Allow some exceptions but most should follow convention
        if len(non_matching) > len(keys) * 0.05:  # More than 5% don't match
            msg = f"{len(non_matching)} keys don't follow CFG-GROUP-NAME pattern:\n"
            for name in non_matching[:10]:
                msg += f"  {name}\n"
            if len(non_matching) > 10:
                msg += f"  ... and {len(non_matching) - 10} more"
            pytest.fail(msg)


class TestConfigKeyProvenance:
    """Test source provenance tracking for config keys."""

    def test_keys_have_sources(self):
        """All config keys should have sources list."""
        keys = get_all_keys()

        missing = []
        for key in keys:
            if "sources" not in key:
                missing.append(key.get("name", "UNNAMED"))
            elif not key["sources"]:
                missing.append(f"{key.get('name')} (empty)")

        if missing:
            msg = "Config keys missing sources:\n"
            for name in missing[:10]:
                msg += f"  {name}\n"
            if len(missing) > 10:
                msg += f"  ... and {len(missing) - 10} more"
            pytest.fail(msg)

    def test_enum_values_have_sources(self):
        """Enum values should have sources list."""
        keys_with_enum = get_keys_with_inline_enum()

        missing = []
        for key in keys_with_enum:
            enum = key.get("inline_enum", {})
            for val_name, val_def in enum.get("values", {}).items():
                if "sources" not in val_def:
                    missing.append(f"{key.get('name')}.{val_name}")
                elif not val_def["sources"]:
                    missing.append(f"{key.get('name')}.{val_name} (empty)")

        if missing:
            msg = "Enum values missing sources:\n"
            for name in missing[:10]:
                msg += f"  {name}\n"
            if len(missing) > 10:
                msg += f"  ... and {len(missing) - 10} more"
            pytest.fail(msg)

    def test_sources_are_valid_manual_ids(self):
        """Sources should be valid manual ID format."""
        keys = get_all_keys()

        # Valid patterns: "F9-HPG-1.51", "M10-SPG-5.30", "F9H", "F9-HPG-L1L5-1.40", "20-HPG-2.00"
        # Allow multiple dash-separated segments ending with version number
        valid_pattern = re.compile(r"^[A-Z0-9]+(-[A-Z0-9.]+)+$|^[A-Z0-9]+$")

        invalid = []
        for key in keys:
            for source in key.get("sources", []):
                if not valid_pattern.match(source):
                    invalid.append((key.get("name"), source))

        if invalid:
            msg = "Invalid source format:\n"
            for key_name, source in invalid[:10]:
                msg += f"  {key_name}: '{source}'\n"
            if len(invalid) > 10:
                msg += f"  ... and {len(invalid) - 10} more"
            pytest.fail(msg)

    def test_dynmodel_provenance_f9h_exclusion(self):
        """F9H should be in DYNMODEL key sources but NOT in BIKE/MOWER enum sources."""
        keys = get_all_keys()

        dynmodel = None
        for key in keys:
            if key.get("name") == "CFG-NAVSPG-DYNMODEL":
                dynmodel = key
                break

        if not dynmodel:
            pytest.skip("CFG-NAVSPG-DYNMODEL not found")

        # F9H should be in key sources (it has the key)
        # Note: The actual source ID may vary, check for F9H-related pattern
        key_sources = dynmodel.get("sources", [])
        f9h_in_key = any("F9H" in s or "ZED-F9H" in s for s in key_sources)

        # Check enum values for BIKE - F9H should NOT be a source
        enum_values = dynmodel.get("inline_enum", {}).get("values", {})
        bike_sources = enum_values.get("BIKE", {}).get("sources", [])

        # If F9H is in key sources but has enum values extracted,
        # BIKE should not be in F9H's enum (timing module exclusion)
        if f9h_in_key and bike_sources:
            f9h_in_bike = any("F9H" in s or "ZED-F9H" in s for s in bike_sources)
            assert not f9h_in_bike, (
                "F9H should not be a source for BIKE enum value "
                "(F9H is a timing module that excludes motion-specific dynamic models)"
            )
