#!/usr/bin/env python3
"""
Merge extracted messages into the main dataset.

Takes messages from data/preliminary/extracted_missing/ and adds them to
data/messages/ubx_messages.json with proper version tracking.

Usage:
    uv run python validation/scripts/merge_extracted.py
    uv run python validation/scripts/merge_extracted.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def load_inventory() -> dict:
    """Load the PDF inventory for version tracking."""
    inventory_file = PROJECT_ROOT / "validation" / "inventory" / "pdf_inventory.json"
    with open(inventory_file) as f:
        return json.load(f)


def load_manual_metadata() -> dict:
    """Load manual metadata for protocol versions."""
    meta_file = PROJECT_ROOT / "data" / "manual_metadata.json"
    if meta_file.exists():
        with open(meta_file) as f:
            return json.load(f)
    return {"manuals": {}}


def load_main_dataset() -> dict:
    """Load the main messages dataset."""
    msgs_file = PROJECT_ROOT / "data" / "messages" / "ubx_messages.json"
    with open(msgs_file) as f:
        return json.load(f)


def load_extracted_messages() -> list[dict]:
    """Load all extracted messages from preliminary directory."""
    extract_dir = PROJECT_ROOT / "data" / "preliminary" / "extracted_missing"
    if not extract_dir.exists():
        return []

    messages = []
    for json_file in sorted(extract_dir.glob("*.json")):
        with open(json_file) as f:
            msg = json.load(f)
            messages.append(msg)

    return messages


def add_version_info(message: dict, inventory: dict, metadata: dict) -> dict:
    """Add supported_versions info to a message based on inventory."""

    msg_name = message["name"]
    manuals = inventory.get("messages", {}).get(msg_name, [])

    # Build protocol version list
    protocol_versions = []
    source_manuals = []

    for manual_name in manuals:
        manual_info = metadata.get("manuals", {}).get(manual_name, {})
        pv = manual_info.get("protocol_version")
        if pv:
            protocol_versions.append(pv)
        source_manuals.append(manual_name)

    # Remove duplicates and sort
    protocol_versions = sorted(set(protocol_versions))

    message["supported_versions"] = {
        "protocol_versions": protocol_versions,
        "min_protocol_version": min(protocol_versions) if protocol_versions else None,
        "source_manuals": sorted(set(source_manuals)),
    }

    return message


def sort_messages(messages: list[dict]) -> list[dict]:
    """Sort messages by class_id, then message_id."""

    def parse_hex(value, default=0):
        """Parse a hex string or return integer as-is."""
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value, 16) if value.startswith("0x") else int(value)
        return default

    def sort_key(msg):
        # Parse hex class_id and message_id
        class_id = parse_hex(msg.get("class_id", "0x00"))
        message_id = parse_hex(msg.get("message_id", "0x00"))
        return (class_id, message_id, msg.get("name", ""))

    return sorted(messages, key=sort_key)


def merge_messages(
    existing: list[dict],
    new_messages: list[dict],
) -> tuple[list[dict], int, int]:
    """
    Merge new messages into existing dataset.

    Returns (merged_list, added_count, updated_count)
    """
    # Build lookup by name
    existing_by_name = {m["name"]: m for m in existing}

    added = 0
    updated = 0

    for new_msg in new_messages:
        name = new_msg["name"]
        if name in existing_by_name:
            # Update existing message
            existing_by_name[name] = new_msg
            updated += 1
        else:
            # Add new message
            existing_by_name[name] = new_msg
            added += 1

    merged = list(existing_by_name.values())
    return merged, added, updated


def main():
    parser = argparse.ArgumentParser(
        description="Merge extracted messages into main dataset"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )

    args = parser.parse_args()

    # Load data
    print("Loading data...")
    inventory = load_inventory()
    metadata = load_manual_metadata()
    dataset = load_main_dataset()
    extracted = load_extracted_messages()

    existing_messages = dataset.get("messages", [])

    print(f"  Existing messages: {len(existing_messages)}")
    print(f"  Extracted messages: {len(extracted)}")

    if not extracted:
        print("No extracted messages to merge.")
        return 0

    # Add version info to each extracted message
    print("\nAdding version info...")
    for msg in extracted:
        add_version_info(msg, inventory, metadata)
        print(f"  {msg['name']}: {len(msg['supported_versions'].get('source_manuals', []))} manuals")

    # Merge
    print("\nMerging...")
    merged, added, updated = merge_messages(existing_messages, extracted)

    # Sort
    merged = sort_messages(merged)

    print(f"  Added: {added}")
    print(f"  Updated: {updated}")
    print(f"  Total: {len(merged)}")

    if args.dry_run:
        print("\n[DRY RUN] No changes made.")
        return 0

    # Save
    dataset["messages"] = merged
    dataset["generated"] = datetime.now(timezone.utc).isoformat()

    output_file = PROJECT_ROOT / "data" / "messages" / "ubx_messages.json"
    with open(output_file, "w") as f:
        json.dump(dataset, f, indent=2)

    print(f"\nSaved to: {output_file}")

    # Show new message classes
    new_classes = set()
    for msg in extracted:
        parts = msg["name"].split("-")
        if len(parts) >= 2:
            new_classes.add(parts[1])

    print(f"\nNew message classes added: {sorted(new_classes)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
