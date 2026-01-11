#!/usr/bin/env python3
"""
Consolidate suffix-named UBX messages into proper variants.

Messages sharing the same Class/Message ID (like UBX-MGA-GPS-EPH, UBX-MGA-GPS-ALM, etc.)
are consolidated into a single message with a variants array.

Usage:
    # Preview changes (dry run)
    uv run python scripts/consolidate_variants.py --dry-run

    # Convert UBX-MGA-GPS family
    uv run python scripts/consolidate_variants.py --family MGA-GPS

    # Convert all known multi-variant families
    uv run python scripts/consolidate_variants.py --all
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Known multi-variant message families from extract_messages_v2.py
VARIANT_FAMILIES = {
    "MGA-GPS": {
        "base_name": "UBX-MGA-GPS",
        "class_id": "0x13",
        "message_id": "0x00",
        "discriminator_field": "type",
        "variants": {
            "EPH": {"value": 1, "suffix": "-EPH"},
            "ALM": {"value": 2, "suffix": "-ALM"},
            "HEALTH": {"value": 4, "suffix": "-HEALTH"},
            "UTC": {"value": 5, "suffix": "-UTC"},
            "IONO": {"value": 6, "suffix": "-IONO"},
        }
    },
    "MGA-GAL": {
        "base_name": "UBX-MGA-GAL",
        "class_id": "0x13",
        "message_id": "0x02",
        "discriminator_field": "type",
        "variants": {
            "EPH": {"value": 1, "suffix": "-EPH"},
            "ALM": {"value": 2, "suffix": "-ALM"},
            "TIMEOFFSET": {"value": 3, "suffix": "-TIMEOFFSET"},
            "UTC": {"value": 5, "suffix": "-UTC"},
        }
    },
    "MGA-BDS": {
        "base_name": "UBX-MGA-BDS",
        "class_id": "0x13",
        "message_id": "0x03",
        "discriminator_field": "type",
        "variants": {
            "EPH": {"value": 1, "suffix": "-EPH"},
            "ALM": {"value": 2, "suffix": "-ALM"},
            "HEALTH": {"value": 4, "suffix": "-HEALTH"},
            "UTC": {"value": 5, "suffix": "-UTC"},
            "IONO": {"value": 6, "suffix": "-IONO"},
        }
    },
    "MGA-GLO": {
        "base_name": "UBX-MGA-GLO",
        "class_id": "0x13",
        "message_id": "0x06",
        "discriminator_field": "type",
        "variants": {
            "EPH": {"value": 1, "suffix": "-EPH"},
            "ALM": {"value": 2, "suffix": "-ALM"},
            "TIMEOFFSET": {"value": 3, "suffix": "-TIMEOFFSET"},
        }
    },
    "MGA-QZSS": {
        "base_name": "UBX-MGA-QZSS",
        "class_id": "0x13",
        "message_id": "0x05",
        "discriminator_field": "type",
        "variants": {
            "EPH": {"value": 1, "suffix": "-EPH"},
            "ALM": {"value": 2, "suffix": "-ALM"},
            "HEALTH": {"value": 4, "suffix": "-HEALTH"},
        }
    },
}


def load_messages(messages_file: Path) -> dict:
    """Load the messages JSON file."""
    with open(messages_file) as f:
        return json.load(f)


def save_messages(data: dict, messages_file: Path) -> None:
    """Save the messages JSON file."""
    with open(messages_file, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def find_variant_messages(messages: list, family: dict) -> dict:
    """Find existing messages that belong to this variant family."""
    found = {}
    base_name = family["base_name"]

    for msg in messages:
        name = msg["name"]
        if name.startswith(base_name + "-"):
            # Extract suffix (e.g., "-EPH" from "UBX-MGA-GPS-EPH")
            suffix = name[len(base_name):]
            for variant_name, variant_info in family["variants"].items():
                if suffix == variant_info["suffix"]:
                    found[variant_name] = msg
                    break

    return found


def extract_type_value_from_description(msg: dict, discriminator_field: str) -> int | None:
    """Extract the type value from the field description."""
    if "payload" not in msg or "fields" not in msg["payload"]:
        return None

    for field in msg["payload"]["fields"]:
        if field["name"] == discriminator_field:
            desc = field.get("description", "")
            # Look for patterns like "0x01", "(0x01)", "type (0x01)"
            match = re.search(r"0x([0-9a-fA-F]+)", desc)
            if match:
                return int(match.group(1), 16)
            # Also try decimal
            match = re.search(r"\((\d+)\s+for", desc)
            if match:
                return int(match.group(1))
    return None


def consolidate_family(messages: list, family_key: str, family: dict, dry_run: bool = True) -> tuple[dict | None, list]:
    """
    Consolidate a family of suffix-named messages into a single message with variants.

    Returns:
        (consolidated_message, removed_message_names) or (None, []) if consolidation not possible
    """
    base_name = family["base_name"]
    found_msgs = find_variant_messages(messages, family)

    if not found_msgs:
        print(f"  No variant messages found for {base_name}")
        return None, []

    print(f"  Found {len(found_msgs)} variants: {', '.join(found_msgs.keys())}")

    # Build the consolidated message
    # Use the first found message as a template for common properties
    first_msg = next(iter(found_msgs.values()))

    # Build variant aliases list
    variant_aliases = [f"{base_name}{info['suffix']}" for info in family["variants"].values()]

    # Build variants array
    variants = []
    for variant_name, variant_info in family["variants"].items():
        if variant_name not in found_msgs:
            print(f"    Warning: Expected variant {variant_name} not found in data")
            continue

        msg = found_msgs[variant_name]

        # Get discriminator value from the family config, or extract from message
        disc_value = variant_info.get("value")
        if disc_value is None:
            disc_value = extract_type_value_from_description(msg, family["discriminator_field"])

        variant = {
            "name": variant_name,
            "discriminator": {
                "field": family["discriminator_field"],
                "byte_offset": 0,
                "value": disc_value
            },
            "payload": msg["payload"]
        }

        if "description" in msg:
            variant["description"] = msg["description"]

        variants.append(variant)

    if not variants:
        print(f"  No variants could be built for {base_name}")
        return None, []

    # Sort variants by discriminator value
    variants.sort(key=lambda v: v["discriminator"]["value"] if v["discriminator"]["value"] is not None else 999)

    # Build consolidated message
    consolidated = {
        "name": base_name,
        "class_id": family["class_id"],
        "message_id": family["message_id"],
        "message_type": first_msg.get("message_type", "input"),
        "description": f"Multiple AssistNow Online message types for {family_key.split('-')[1]} constellation",
    }

    # Merge supported_versions from all variants
    all_protocol_versions = set()
    all_source_manuals = set()
    for msg in found_msgs.values():
        if "supported_versions" in msg:
            sv = msg["supported_versions"]
            if "protocol_versions" in sv:
                all_protocol_versions.update(sv["protocol_versions"])
            if "source_manuals" in sv:
                all_source_manuals.update(sv["source_manuals"])

    if all_protocol_versions:
        consolidated["supported_versions"] = {
            "protocol_versions": sorted(all_protocol_versions),
            "min_protocol_version": min(all_protocol_versions),
            "source_manuals": sorted(all_source_manuals)
        }

    # Add variant_aliases for backward compatibility
    consolidated["variant_aliases"] = variant_aliases

    # Add variants array
    consolidated["variants"] = variants

    removed_names = [msg["name"] for msg in found_msgs.values()]

    if dry_run:
        print(f"\n  Would create consolidated message: {base_name}")
        print(f"  With {len(variants)} variants: {[v['name'] for v in variants]}")
        print(f"  Would remove {len(removed_names)} messages: {removed_names}")
    else:
        print(f"\n  Created consolidated message: {base_name}")
        print(f"  With {len(variants)} variants")
        print(f"  Removed {len(removed_names)} individual messages")

    return consolidated, removed_names


def main():
    parser = argparse.ArgumentParser(description="Consolidate suffix-named messages into variants")
    parser.add_argument("--family", choices=list(VARIANT_FAMILIES.keys()),
                        help="Consolidate a specific family")
    parser.add_argument("--all", action="store_true",
                        help="Consolidate all known variant families")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without modifying files")
    parser.add_argument("--messages-file", type=Path,
                        default=Path("data/messages/ubx_messages.json"),
                        help="Path to messages file")

    args = parser.parse_args()

    if not args.family and not args.all:
        parser.error("Must specify --family or --all")

    if not args.messages_file.exists():
        print(f"Error: Messages file not found: {args.messages_file}")
        sys.exit(1)

    print(f"Loading messages from {args.messages_file}")
    data = load_messages(args.messages_file)
    messages = data["messages"]
    print(f"  Loaded {len(messages)} messages")

    families_to_process = [args.family] if args.family else list(VARIANT_FAMILIES.keys())

    total_consolidated = 0
    total_removed = 0

    for family_key in families_to_process:
        print(f"\nProcessing family: {family_key}")
        family = VARIANT_FAMILIES[family_key]

        consolidated, removed_names = consolidate_family(
            messages, family_key, family, dry_run=args.dry_run
        )

        if consolidated:
            if not args.dry_run:
                # Remove individual messages
                messages = [m for m in messages if m["name"] not in removed_names]
                # Add consolidated message
                messages.append(consolidated)
                total_consolidated += 1
                total_removed += len(removed_names)
            else:
                total_consolidated += 1
                total_removed += len(removed_names)

    if not args.dry_run and total_consolidated > 0:
        # Sort messages by name
        messages.sort(key=lambda m: m["name"])
        data["messages"] = messages

        print(f"\nSaving {len(messages)} messages to {args.messages_file}")
        save_messages(data, args.messages_file)
        print("Done!")

    print(f"\nSummary:")
    print(f"  Families consolidated: {total_consolidated}")
    print(f"  Individual messages {'would be ' if args.dry_run else ''}removed: {total_removed}")
    print(f"  Final message count: {len(messages) - total_removed + total_consolidated if args.dry_run else len(messages)}")


if __name__ == "__main__":
    main()
