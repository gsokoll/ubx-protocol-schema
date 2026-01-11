#!/usr/bin/env python3
"""
Cross-validate our schema against pyubx2 (and optionally ublox-rs).

This script COMPARES but does NOT copy. It identifies:
- Fields we have that pyubx2 doesn't
- Fields pyubx2 has that we don't
- Bitfield differences
- Type mismatches

Uses a mapping file to handle known naming differences between our
canonical schema (from u-blox manuals) and pyubx2 conventions.

Usage:
    uv run python validation/scripts/cross_validate.py UBX-NAV-PVT
    uv run python validation/scripts/cross_validate.py --all
    uv run python validation/scripts/cross_validate.py --all --strict  # Show only real issues
    uv run python validation/scripts/cross_validate.py --summary
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
MAPPING_FILE = Path(__file__).parent.parent / "pyubx2_mapping.json"
sys.path.insert(0, str(PROJECT_ROOT))


# Global mapping cache
_mapping: dict | None = None


def load_mapping() -> dict:
    """Load the pyubx2 mapping file."""
    global _mapping
    if _mapping is None:
        if MAPPING_FILE.exists():
            with open(MAPPING_FILE) as f:
                _mapping = json.load(f)
        else:
            _mapping = {}
    return _mapping


def get_field_alias(our_name: str) -> str | None:
    """Get pyubx2 alias for our field name."""
    mapping = load_mapping()
    aliases = mapping.get("field_aliases", {})
    return aliases.get(our_name)


def get_bitfield_alias(our_name: str) -> str | None:
    """Get pyubx2 alias for our bitfield bit name."""
    mapping = load_mapping()
    aliases = mapping.get("bitfield_aliases", {})
    return aliases.get(our_name)


def is_repeated_group_field(field_name: str) -> bool:
    """Check if field name matches pyubx2 repeated group pattern."""
    mapping = load_mapping()
    patterns = mapping.get("repeated_group_patterns", {}).get("patterns", [])
    for pattern in patterns:
        if re.match(pattern, field_name):
            return True
    return False


def is_expected_extra_field(message_name: str, field_name: str) -> bool:
    """Check if pyubx2 field is an expected extra (different representation)."""
    mapping = load_mapping()
    extra_fields = mapping.get("extra_pyubx2_fields", {})
    return field_name in extra_fields.get(message_name, [])


def get_hp_field_mapping(message_name: str) -> dict:
    """Get high-precision field mappings for a message."""
    mapping = load_mapping()
    return mapping.get("expanded_hp_fields", {}).get(message_name, {})


def is_type_equivalent(message_name: str, field_name: str, our_type: str, pyubx_type: str) -> bool:
    """Check if types are equivalent per mapping (e.g., X1=U1 for bitfield vs integer)."""
    mapping = load_mapping()
    type_equivs = mapping.get("type_equivalences", {}).get(message_name, {})
    if field_name in type_equivs:
        equiv = type_equivs[field_name]
        # equiv is like "X1=U1"
        parts = equiv.split("=")
        if len(parts) == 2:
            our_norm = normalize_type(our_type)
            pyubx_norm = normalize_type(pyubx_type)
            return (our_norm == parts[0] and pyubx_norm == parts[1]) or \
                   (our_norm == parts[1] and pyubx_norm == parts[0])
    return False


@dataclass
class ComparisonResult:
    """Result of comparing a message against external library."""
    message: str
    library: str
    found_in_library: bool
    field_differences: list[dict] = field(default_factory=list)
    bitfield_differences: list[dict] = field(default_factory=list)
    our_only_fields: list[str] = field(default_factory=list)
    library_only_fields: list[str] = field(default_factory=list)
    mapped_field_aliases: list[tuple] = field(default_factory=list)
    mapped_bit_aliases: list[tuple] = field(default_factory=list)
    ignored_repeated_groups: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "message": self.message,
            "library": self.library,
            "found_in_library": self.found_in_library,
            "field_differences": self.field_differences,
            "bitfield_differences": self.bitfield_differences,
            "our_only_fields": self.our_only_fields,
            "library_only_fields": self.library_only_fields,
            "mapped_field_aliases": self.mapped_field_aliases,
            "mapped_bit_aliases": self.mapped_bit_aliases,
            "ignored_repeated_groups": self.ignored_repeated_groups,
            "notes": self.notes,
        }

    @property
    def has_differences(self) -> bool:
        """Check if there are any unresolved differences."""
        return bool(
            self.field_differences
            or self.bitfield_differences
            or self.our_only_fields
            or self.library_only_fields
        )

    @property
    def has_real_issues(self) -> bool:
        """Check if there are structural issues (not just naming)."""
        # Real issues are type mismatches, offset/width mismatches, missing bitfields
        for d in self.field_differences:
            if d.get("issue") == "type_mismatch":
                return True
        for d in self.bitfield_differences:
            if d.get("issue") in ("offset mismatch", "width mismatch", "missing_bitfield"):
                return True
        return False


def load_our_messages() -> dict[str, dict]:
    """Load our canonical message definitions."""
    msgs_file = PROJECT_ROOT / "data" / "messages" / "ubx_messages.json"
    with open(msgs_file) as f:
        data = json.load(f)
    return {m["name"]: m for m in data.get("messages", [])}


def get_pyubx2_message(message_name: str) -> dict | None:
    """Get message definition from pyubx2."""
    try:
        from pyubx2.ubxmessage import UBX_PAYLOADS_GET, UBX_PAYLOADS_SET, UBX_PAYLOADS_POLL

        # Convert our name format to pyubx2 format
        # UBX-NAV-PVT -> NAV-PVT
        pyubx_name = message_name.replace("UBX-", "")

        # Check all payload dicts
        for payloads in [UBX_PAYLOADS_GET, UBX_PAYLOADS_SET, UBX_PAYLOADS_POLL]:
            if pyubx_name in payloads:
                return payloads[pyubx_name]

        return None
    except ImportError:
        return None


def parse_pyubx2_type(type_str: str | list | tuple) -> dict:
    """Parse pyubx2 type definition into our format."""
    if isinstance(type_str, list):
        # Scaled value: ['I004', 1e-07]
        return {"type": type_str[0], "scale": type_str[1]}
    elif isinstance(type_str, tuple) and len(type_str) == 2:
        # Bitfield or group: ('X001', {...}) or ('numSvs', {...})
        type_or_count, content = type_str
        if isinstance(type_or_count, str) and type_or_count.startswith("X"):
            return {"type": type_or_count, "bitfield": content}
        else:
            return {"type": "group", "count_field": type_or_count, "fields": content}
    elif isinstance(type_str, str):
        return {"type": type_str}
    return {"type": str(type_str)}


def normalize_type(t: str) -> str:
    """Normalize type string for comparison."""
    # pyubx2 uses U004, we use U4
    if len(t) == 4 and t[0] in "UIXRC" and t[1:].isdigit():
        return t[0] + str(int(t[1:]))
    # Handle character arrays: CH[30] -> C30, C030 -> C30
    if t.startswith("CH[") and t.endswith("]"):
        return "C" + t[3:-1]
    return t


def compare_bitfields(our_bitfield: list, pyubx_bitfield: dict, result: ComparisonResult) -> list[dict]:
    """Compare bitfield definitions, applying name mappings."""
    differences = []

    # Convert our format to dict by name
    our_bits = {}
    if our_bitfield and isinstance(our_bitfield, list):
        for b in our_bitfield:
            if isinstance(b, dict) and "name" in b:
                our_bits[b["name"]] = b

    # pyubx2 bitfield is a dict: {"bitName": "U001", ...}
    pyubx_bits = {}
    bit_offset = 0
    for name, width_str in pyubx_bitfield.items():
        if isinstance(width_str, str) and width_str.startswith("U"):
            width = int(width_str[1:])
        else:
            width = 1
        pyubx_bits[name] = {"bit_offset": bit_offset, "width": width}
        bit_offset += width

    # Build mappings: our name -> pyubx name (considering aliases)
    our_to_pyubx = {}
    for our_name in our_bits:
        # Check if there's a direct match
        if our_name in pyubx_bits:
            our_to_pyubx[our_name] = our_name
        else:
            # Check for alias
            alias = get_bitfield_alias(our_name)
            if alias and alias in pyubx_bits:
                our_to_pyubx[our_name] = alias
                result.mapped_bit_aliases.append((our_name, alias))

    # Find unmatched names
    matched_pyubx = set(our_to_pyubx.values())

    for our_name in our_bits:
        if our_name not in our_to_pyubx:
            if not our_name.startswith("reserved"):
                differences.append({
                    "bit": our_name,
                    "issue": "only in our schema",
                })

    for pyubx_name in pyubx_bits:
        if pyubx_name not in matched_pyubx:
            if not pyubx_name.startswith("reserved"):
                differences.append({
                    "bit": pyubx_name,
                    "issue": "only in pyubx2",
                    "pyubx2_offset": pyubx_bits[pyubx_name]["bit_offset"],
                    "pyubx2_width": pyubx_bits[pyubx_name]["width"],
                })

    # Compare matched bits
    for our_name, pyubx_name in our_to_pyubx.items():
        our_b = our_bits[our_name]
        pyubx_b = pyubx_bits[pyubx_name]

        if our_b.get("bit_offset") != pyubx_b["bit_offset"]:
            differences.append({
                "bit": our_name,
                "issue": "offset mismatch",
                "our_offset": our_b.get("bit_offset"),
                "pyubx2_offset": pyubx_b["bit_offset"],
            })

        our_width = our_b.get("bit_width") or our_b.get("width")
        if our_width != pyubx_b["width"]:
            differences.append({
                "bit": our_name,
                "issue": "width mismatch",
                "our_width": our_width,
                "pyubx2_width": pyubx_b["width"],
            })

    return differences


def compare_message_with_pyubx2(message_name: str, our_message: dict) -> ComparisonResult:
    """Compare our message definition with pyubx2."""
    result = ComparisonResult(
        message=message_name,
        library="pyubx2",
        found_in_library=False,
    )

    pyubx_def = get_pyubx2_message(message_name)
    if not pyubx_def:
        result.notes = "Message not found in pyubx2"
        return result

    result.found_in_library = True

    # Get our fields
    our_fields = {}
    for f in our_message.get("payload", {}).get("fields", []):
        our_fields[f["name"]] = f

    # Parse pyubx2 fields
    pyubx_fields = {}
    for name, type_def in pyubx_def.items():
        parsed = parse_pyubx2_type(type_def)
        pyubx_fields[name] = parsed

    # Build field mappings (our name -> pyubx name)
    our_to_pyubx = {}
    hp_mapping = get_hp_field_mapping(message_name)

    for our_name in our_fields:
        # Direct match
        if our_name in pyubx_fields:
            our_to_pyubx[our_name] = our_name
        # Alias match
        elif get_field_alias(our_name) in pyubx_fields:
            alias = get_field_alias(our_name)
            our_to_pyubx[our_name] = alias
            result.mapped_field_aliases.append((our_name, alias))
        # HP field mapping
        elif our_name in hp_mapping and hp_mapping[our_name] in pyubx_fields:
            our_to_pyubx[our_name] = hp_mapping[our_name]
            result.mapped_field_aliases.append((our_name, hp_mapping[our_name]))

    # Find unmatched fields
    matched_pyubx = set(our_to_pyubx.values())

    for our_name in our_fields:
        if our_name not in our_to_pyubx:
            if not our_name.startswith("reserved"):
                result.our_only_fields.append(our_name)

    for pyubx_name in pyubx_fields:
        if pyubx_name not in matched_pyubx:
            if pyubx_name.startswith("reserved") or pyubx_name == "group":
                continue
            # Check if it's a repeated group expansion or expected extra
            if is_repeated_group_field(pyubx_name):
                result.ignored_repeated_groups.append(pyubx_name)
            elif is_expected_extra_field(message_name, pyubx_name):
                result.ignored_repeated_groups.append(pyubx_name)
            else:
                result.library_only_fields.append(pyubx_name)

    # Compare matched fields
    for our_name, pyubx_name in our_to_pyubx.items():
        our_f = our_fields[our_name]
        pyubx_f = pyubx_fields[pyubx_name]

        # Skip reserved field comparisons - naming conventions differ
        # (we use 0-indexed, pyubx2 uses 1-indexed) and they're just padding
        if our_name.startswith("reserved"):
            continue

        our_type = our_f.get("data_type", "")
        pyubx_type = pyubx_f.get("type", "")

        # Normalize types for comparison
        if isinstance(our_type, str) and isinstance(pyubx_type, str):
            our_norm = normalize_type(our_type)
            pyubx_norm = normalize_type(pyubx_type)

            if our_norm != pyubx_norm:
                # Check if types are equivalent per mapping (e.g., X1=U1)
                if not is_type_equivalent(message_name, our_name, our_type, pyubx_type):
                    result.field_differences.append({
                        "field": our_name,
                        "issue": "type_mismatch",
                        "our_type": our_type,
                        "pyubx2_type": pyubx_type,
                    })

        # Compare bitfields if applicable
        if isinstance(our_type, str) and our_type.startswith("X") and "bitfield" in pyubx_f:
            our_bitfield = our_f.get("bitfield", [])
            pyubx_bitfield = pyubx_f["bitfield"]

            if not our_bitfield:
                result.bitfield_differences.append({
                    "field": our_name,
                    "issue": "missing_bitfield",
                    "notes": "We have X-type but no bitfield definition",
                })
            else:
                bit_diffs = compare_bitfields(our_bitfield, pyubx_bitfield, result)
                for d in bit_diffs:
                    d["field"] = our_name
                    result.bitfield_differences.append(d)

    return result


def cross_validate_message(message_name: str, verbose: bool = False, strict: bool = False) -> ComparisonResult:
    """Cross-validate a single message against external libraries."""
    our_messages = load_our_messages()

    if message_name not in our_messages:
        print(f"Error: Message '{message_name}' not found in our schema")
        return ComparisonResult(
            message=message_name,
            library="pyubx2",
            found_in_library=False,
            notes="Message not in our schema",
        )

    our_message = our_messages[message_name]
    result = compare_message_with_pyubx2(message_name, our_message)

    if verbose:
        print(f"\n=== {message_name} vs pyubx2 ===")
        if not result.found_in_library:
            print(f"  Not found in pyubx2")
        else:
            if result.mapped_field_aliases:
                print(f"  Mapped field aliases: {result.mapped_field_aliases}")
            if result.mapped_bit_aliases:
                print(f"  Mapped bit aliases: {result.mapped_bit_aliases}")
            if result.ignored_repeated_groups:
                print(f"  Ignored repeated groups: {result.ignored_repeated_groups}")
            if result.our_only_fields:
                print(f"  Fields only in ours: {result.our_only_fields}")
            if result.library_only_fields:
                print(f"  Fields only in pyubx2: {result.library_only_fields}")
            if result.field_differences:
                print(f"  Field differences:")
                for d in result.field_differences:
                    print(f"    {d['field']}: {d['issue']}")
            if result.bitfield_differences:
                print(f"  Bitfield differences:")
                for d in result.bitfield_differences:
                    print(f"    {d['field']}.{d.get('bit', '?')}: {d['issue']}")
            if not result.has_differences:
                print(f"  OK - No unresolved differences")
            elif not result.has_real_issues:
                print(f"  OK - Only naming differences (no structural issues)")

    return result


def cross_validate_all(verbose: bool = False, strict: bool = False) -> dict:
    """Cross-validate all messages."""
    our_messages = load_our_messages()

    results = []
    stats = {
        "total": 0,
        "found_in_pyubx2": 0,
        "with_differences": 0,
        "with_real_issues": 0,
        "missing_bitfields": 0,
        "fully_matched": 0,
    }

    for message_name in sorted(our_messages.keys()):
        result = cross_validate_message(message_name, verbose=False, strict=strict)
        results.append(result)

        stats["total"] += 1
        if result.found_in_library:
            stats["found_in_pyubx2"] += 1
        if result.has_differences:
            stats["with_differences"] += 1
        if result.has_real_issues:
            stats["with_real_issues"] += 1
        if any(d.get("issue") == "missing_bitfield" for d in result.bitfield_differences):
            stats["missing_bitfields"] += 1
        if result.found_in_library and not result.has_differences:
            stats["fully_matched"] += 1

    if verbose:
        print("\n=== Messages with differences ===")
        for r in results:
            show = r.has_real_issues if strict else r.has_differences
            if show:
                print(f"\n{r.message}:")
                if r.library_only_fields:
                    print(f"  pyubx2 has extra fields: {r.library_only_fields}")
                if r.our_only_fields:
                    print(f"  our schema has extra fields: {r.our_only_fields}")
                for d in r.bitfield_differences:
                    print(f"  {d['field']}: {d['issue']}")
                for d in r.field_differences:
                    print(f"  {d['field']}: {d['issue']}")

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
        "results": [r.to_dict() for r in results],
    }


def show_summary():
    """Show summary of cross-validation status."""
    our_messages = load_our_messages()

    found = 0
    not_found = 0
    missing_bitfields = 0

    for msg_name, msg in our_messages.items():
        pyubx_def = get_pyubx2_message(msg_name)
        if pyubx_def:
            found += 1
        else:
            not_found += 1

        for f in msg.get("payload", {}).get("fields", []):
            dt = f.get("data_type", "")
            if isinstance(dt, str) and dt.startswith("X") and "bitfield" not in f:
                missing_bitfields += 1

    print("=== Cross-Validation Summary ===")
    print(f"Total messages in our schema: {len(our_messages)}")
    print(f"Found in pyubx2: {found}")
    print(f"Not in pyubx2: {not_found}")
    print(f"X-type fields missing bitfields: {missing_bitfields}")


def main():
    parser = argparse.ArgumentParser(
        description="Cross-validate schema against pyubx2"
    )
    parser.add_argument(
        "message",
        nargs="?",
        help="Message name (e.g., UBX-NAV-PVT)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate all messages"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show summary only"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Only show structural issues (not naming differences)"
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save results to file"
    )

    args = parser.parse_args()

    # Check pyubx2 is available
    try:
        import pyubx2
    except ImportError:
        print("Error: pyubx2 not installed")
        print("Install with: uv add pyubx2")
        return 1

    if args.summary:
        show_summary()
        return 0

    if args.all:
        results = cross_validate_all(verbose=args.verbose, strict=args.strict)
        stats = results["stats"]
        print(f"\n=== Summary ===")
        print(f"  Total messages: {stats['total']}")
        print(f"  Found in pyubx2: {stats['found_in_pyubx2']}")
        print(f"  Fully matched: {stats['fully_matched']}")
        print(f"  With naming differences: {stats['with_differences'] - stats['with_real_issues']}")
        print(f"  With structural issues: {stats['with_real_issues']}")
        print(f"  Missing bitfields: {stats['missing_bitfields']}")

        if args.save:
            output_file = PROJECT_ROOT / "validation" / "reports" / "cross_validation.json"
            with open(output_file, "w") as f:
                json.dump(results, f, indent=2)
            print(f"\nSaved to {output_file}")

        return 0

    if not args.message:
        parser.print_help()
        return 1

    result = cross_validate_message(args.message, verbose=True, strict=args.strict)

    if args.save:
        safe_name = args.message.replace("-", "_")
        output_file = PROJECT_ROOT / "validation" / "reports" / f"{safe_name}_crossval.json"
        with open(output_file, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        print(f"\nSaved to {output_file}")

    return 0 if not result.has_real_issues else 1


if __name__ == "__main__":
    sys.exit(main())
