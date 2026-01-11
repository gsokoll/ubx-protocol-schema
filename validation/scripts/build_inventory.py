#!/usr/bin/env python3
"""
Build ground truth inventory by scanning PDF table of contents.

Extracts all UBX-* message names from each PDF manual's TOC.
This establishes what SHOULD exist in the dataset.

Usage:
    uv run python validation/scripts/build_inventory.py
    uv run python validation/scripts/build_inventory.py --verbose
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF

PROJECT_ROOT = Path(__file__).parent.parent.parent


@dataclass
class ManualInventory:
    """Inventory of messages found in a single manual."""
    manual_name: str
    pdf_path: str
    messages: list[str] = field(default_factory=list)
    config_groups: list[str] = field(default_factory=list)
    toc_entries: int = 0
    ubx_entries: int = 0

    def to_dict(self) -> dict:
        return {
            "manual_name": self.manual_name,
            "pdf_path": self.pdf_path,
            "messages": sorted(set(self.messages)),
            "config_groups": sorted(set(self.config_groups)),
            "message_count": len(set(self.messages)),
            "config_group_count": len(set(self.config_groups)),
            "toc_entries": self.toc_entries,
            "ubx_entries": self.ubx_entries,
        }


def normalize_message_name(toc_title: str) -> str | None:
    """
    Extract normalized message name from TOC entry.

    Examples:
        "3.9.1 UBX-ACK-ACK (0x05 0x01)" -> "UBX-ACK-ACK"
        "UBX-NAV-PVT" -> "UBX-NAV-PVT"
        "3.14 UBX-NAV (0x01)" -> None (class header, not individual message)
    """
    # Pattern for individual message entries (level 3 in TOC)
    # They have format like "UBX-CLASS-MSG" with at least 2 hyphens
    match = re.search(r'(UBX-[A-Z0-9]+-[A-Z0-9]+(?:-[A-Z0-9]+)*)', toc_title)
    if match:
        return match.group(1)
    return None


def extract_config_group(toc_title: str) -> str | None:
    """
    Extract config key group name from TOC entry.

    Examples:
        "5.1.1 CFG-BATCH" -> "CFG-BATCH"
        "CFG-MSGOUT" -> "CFG-MSGOUT"
    """
    match = re.search(r'(CFG-[A-Z0-9]+)', toc_title)
    if match:
        name = match.group(1)
        # Exclude message classes (CFG-VALDEL, CFG-VALGET, CFG-VALSET are messages, not config groups)
        if name not in ('CFG-VALDEL', 'CFG-VALGET', 'CFG-VALSET', 'CFG-MSG', 'CFG-RST', 'CFG-PRT', 'CFG-CFG', 'CFG-OTP'):
            return name
    return None


def scan_pdf_toc(pdf_path: Path, verbose: bool = False) -> ManualInventory:
    """Scan a PDF's table of contents for UBX messages and config groups."""

    inventory = ManualInventory(
        manual_name=pdf_path.stem,
        pdf_path=str(pdf_path.relative_to(PROJECT_ROOT)),
    )

    try:
        doc = fitz.open(pdf_path)
        toc = doc.get_toc()
        doc.close()
    except Exception as e:
        print(f"  Error reading {pdf_path.name}: {e}")
        return inventory

    inventory.toc_entries = len(toc)

    for level, title, page in toc:
        # Messages are typically at level 3 (section 3.x.y)
        # Config groups are typically at level 3 (section 5.x.y)

        if "UBX-" in title:
            inventory.ubx_entries += 1
            msg_name = normalize_message_name(title)
            if msg_name:
                inventory.messages.append(msg_name)
                if verbose:
                    print(f"    Found message: {msg_name}")

        # Look for config key groups in configuration section
        if "CFG-" in title and "UBX-CFG" not in title:
            group_name = extract_config_group(title)
            if group_name:
                inventory.config_groups.append(group_name)
                if verbose:
                    print(f"    Found config group: {group_name}")

    return inventory


def find_all_pdfs() -> list[Path]:
    """Find all PDF manuals."""
    manuals_dir = PROJECT_ROOT / "interface_manuals"
    return sorted(manuals_dir.rglob("*.pdf"))


def build_inventory(verbose: bool = False) -> dict:
    """Build complete inventory from all PDF manuals."""

    pdfs = find_all_pdfs()
    print(f"Found {len(pdfs)} PDF manuals")

    inventories = []
    all_messages = defaultdict(list)  # message -> list of manuals
    all_config_groups = defaultdict(list)  # group -> list of manuals

    for pdf_path in pdfs:
        print(f"Scanning {pdf_path.name}...")
        inv = scan_pdf_toc(pdf_path, verbose=verbose)
        inventories.append(inv)

        # Track which manuals contain each message
        for msg in set(inv.messages):
            all_messages[msg].append(inv.manual_name)

        for grp in set(inv.config_groups):
            all_config_groups[grp].append(inv.manual_name)

        print(f"  {len(set(inv.messages))} messages, {len(set(inv.config_groups))} config groups")

    # Build summary
    summary = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "total_pdfs": len(pdfs),
        "unique_messages": len(all_messages),
        "unique_config_groups": len(all_config_groups),
        "messages": {
            name: sorted(manuals) for name, manuals in sorted(all_messages.items())
        },
        "config_groups": {
            name: sorted(manuals) for name, manuals in sorted(all_config_groups.items())
        },
        "by_manual": [inv.to_dict() for inv in inventories],
    }

    return summary


def save_inventory(inventory: dict):
    """Save inventory to JSON files."""

    output_dir = PROJECT_ROOT / "validation" / "inventory"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Main inventory file
    main_file = output_dir / "pdf_inventory.json"
    with open(main_file, "w") as f:
        json.dump(inventory, f, indent=2)
    print(f"\nSaved inventory to: {main_file}")

    # Quick reference: just the message list
    messages_file = output_dir / "all_messages.json"
    with open(messages_file, "w") as f:
        json.dump({
            "generated": inventory["generated"],
            "message_count": inventory["unique_messages"],
            "messages": sorted(inventory["messages"].keys()),
        }, f, indent=2)
    print(f"Saved message list to: {messages_file}")

    # Quick reference: just the config groups
    config_file = output_dir / "all_config_groups.json"
    with open(config_file, "w") as f:
        json.dump({
            "generated": inventory["generated"],
            "config_group_count": inventory["unique_config_groups"],
            "config_groups": sorted(inventory["config_groups"].keys()),
        }, f, indent=2)
    print(f"Saved config groups to: {config_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Build ground truth inventory from PDF TOCs"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output"
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save results to file"
    )

    args = parser.parse_args()

    inventory = build_inventory(verbose=args.verbose)

    print(f"\n=== Inventory Summary ===")
    print(f"PDFs scanned: {inventory['total_pdfs']}")
    print(f"Unique messages: {inventory['unique_messages']}")
    print(f"Unique config groups: {inventory['unique_config_groups']}")

    if not args.no_save:
        save_inventory(inventory)

    return 0


if __name__ == "__main__":
    sys.exit(main())
