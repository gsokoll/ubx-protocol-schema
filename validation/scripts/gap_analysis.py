#!/usr/bin/env python3
"""
Gap analysis: compare PDF inventory against current dataset.

Identifies:
- MISSING: Messages in PDFs but not in dataset
- ORPHANED: Messages in dataset but not found in any PDF
- Coverage statistics per manual

Usage:
    uv run python validation/scripts/gap_analysis.py
    uv run python validation/scripts/gap_analysis.py --verbose
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def load_inventory() -> dict:
    """Load the PDF inventory."""
    inventory_file = PROJECT_ROOT / "validation" / "inventory" / "pdf_inventory.json"
    if not inventory_file.exists():
        print("Error: Inventory not found. Run build_inventory.py first.")
        sys.exit(1)
    with open(inventory_file) as f:
        return json.load(f)


def load_dataset_messages() -> set[str]:
    """Load message names from the current dataset."""
    msgs_file = PROJECT_ROOT / "data" / "messages" / "ubx_messages.json"
    with open(msgs_file) as f:
        data = json.load(f)
    return {m["name"] for m in data.get("messages", [])}


def load_dataset_config_keys() -> dict:
    """Load config keys from the current dataset."""
    keys_file = PROJECT_ROOT / "data" / "config_keys" / "unified_config_keys.json"
    if not keys_file.exists():
        return {"groups": {}}
    with open(keys_file) as f:
        return json.load(f)


def match_variants(pdf_messages: set[str], dataset_messages: set[str]) -> dict:
    """
    Match PDF base names to dataset variant names.

    Returns dict mapping base_name -> list of variant names found in dataset.
    """
    matches = {}

    for pdf_msg in pdf_messages:
        # Find dataset messages that start with this base name
        variants = [ds_msg for ds_msg in dataset_messages if ds_msg.startswith(pdf_msg + "-")]
        if variants:
            matches[pdf_msg] = variants

    return matches


def analyze_messages(inventory: dict, dataset_messages: set[str], verbose: bool = False) -> dict:
    """Analyze message coverage."""

    pdf_messages = set(inventory["messages"].keys())

    # First pass: direct matches
    direct_covered = pdf_messages & dataset_messages

    # Find variant matches (PDF base name -> dataset variant)
    variant_matches = match_variants(pdf_messages, dataset_messages)

    # Messages that are covered by variants
    variant_covered = set(variant_matches.keys())

    # All covered messages
    covered = direct_covered | variant_covered

    # Missing: in PDFs but not covered by direct or variant match
    missing = pdf_messages - covered

    # Orphaned: in dataset but not matching any PDF name (direct or as variant)
    pdf_bases = pdf_messages.copy()
    matched_variants = set()
    for variants in variant_matches.values():
        matched_variants.update(variants)

    orphaned = dataset_messages - pdf_messages - matched_variants

    # Categorize missing messages by type
    missing_by_class = {}
    for msg in sorted(missing):
        parts = msg.split("-")
        if len(parts) >= 2:
            msg_class = parts[1]  # ACK, CFG, NAV, etc.
            if msg_class not in missing_by_class:
                missing_by_class[msg_class] = []
            missing_by_class[msg_class].append(msg)

    # Find which manuals have each missing message
    missing_details = {}
    for msg in sorted(missing):
        manuals = inventory["messages"].get(msg, [])
        missing_details[msg] = {
            "manuals": manuals,
            "manual_count": len(manuals),
        }

    result = {
        "summary": {
            "pdf_messages": len(pdf_messages),
            "dataset_messages": len(dataset_messages),
            "direct_matches": len(direct_covered),
            "variant_matches": len(variant_covered),
            "covered": len(covered),
            "missing_from_dataset": len(missing),
            "orphaned_in_dataset": len(orphaned),
            "coverage_percent": round(100 * len(covered) / len(pdf_messages), 1) if pdf_messages else 0,
        },
        "missing": missing_details,
        "missing_by_class": {k: sorted(v) for k, v in sorted(missing_by_class.items())},
        "orphaned": sorted(orphaned),
        "variant_matches": {k: sorted(v) for k, v in sorted(variant_matches.items())},
    }

    if verbose:
        print("\n=== Missing Messages (in PDFs but not in dataset) ===")
        for msg_class, msgs in sorted(missing_by_class.items()):
            print(f"\n{msg_class} class ({len(msgs)} missing):")
            for msg in msgs:
                manual_count = len(inventory["messages"].get(msg, []))
                print(f"  {msg} (in {manual_count} manuals)")

        if orphaned:
            print("\n=== Orphaned Messages (in dataset but not in PDFs) ===")
            for msg in sorted(orphaned):
                print(f"  {msg}")

    return result


def analyze_config_groups(inventory: dict, dataset_keys: dict, verbose: bool = False) -> dict:
    """Analyze config key group coverage."""

    pdf_groups = set(inventory.get("config_groups", {}).keys())
    dataset_groups = set(dataset_keys.get("groups", {}).keys())

    missing = pdf_groups - dataset_groups
    orphaned = dataset_groups - pdf_groups
    covered = pdf_groups & dataset_groups

    result = {
        "summary": {
            "pdf_groups": len(pdf_groups),
            "dataset_groups": len(dataset_groups),
            "covered": len(covered),
            "missing_from_dataset": len(missing),
            "orphaned_in_dataset": len(orphaned),
            "coverage_percent": round(100 * len(covered) / len(pdf_groups), 1) if pdf_groups else 0,
        },
        "missing": sorted(missing),
        "orphaned": sorted(orphaned),
    }

    if verbose and missing:
        print("\n=== Missing Config Groups ===")
        for grp in sorted(missing):
            manual_count = len(inventory.get("config_groups", {}).get(grp, []))
            print(f"  {grp} (in {manual_count} manuals)")

    return result


def generate_report(inventory: dict, verbose: bool = False) -> dict:
    """Generate complete gap analysis report."""

    dataset_messages = load_dataset_messages()
    dataset_keys = load_dataset_config_keys()

    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "messages": analyze_messages(inventory, dataset_messages, verbose=verbose),
        "config_groups": analyze_config_groups(inventory, dataset_keys, verbose=verbose),
    }

    return report


def save_report(report: dict):
    """Save gap analysis report."""

    output_dir = PROJECT_ROOT / "validation" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    report_file = output_dir / "gap_analysis.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved report to: {report_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Gap analysis: compare PDF inventory against dataset"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output"
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save report to file"
    )

    args = parser.parse_args()

    # Load inventory
    inventory = load_inventory()

    # Generate report
    report = generate_report(inventory, verbose=args.verbose)

    # Print summary
    msg_summary = report["messages"]["summary"]
    cfg_summary = report["config_groups"]["summary"]

    print("\n" + "=" * 60)
    print("GAP ANALYSIS SUMMARY")
    print("=" * 60)

    print("\n--- Messages ---")
    print(f"In PDFs:              {msg_summary['pdf_messages']}")
    print(f"In dataset:           {msg_summary['dataset_messages']}")
    print(f"  Direct matches:     {msg_summary['direct_matches']}")
    print(f"  Variant matches:    {msg_summary['variant_matches']} (base name has dataset variants)")
    print(f"Coverage:             {msg_summary['coverage_percent']}%")
    print(f"MISSING from dataset: {msg_summary['missing_from_dataset']}")
    print(f"ORPHANED in dataset:  {msg_summary['orphaned_in_dataset']}")

    print("\n--- Config Groups ---")
    print(f"In PDFs:              {cfg_summary['pdf_groups']}")
    print(f"In dataset:           {cfg_summary['dataset_groups']}")
    print(f"Coverage:             {cfg_summary['coverage_percent']}%")
    print(f"MISSING from dataset: {cfg_summary['missing_from_dataset']}")
    print(f"ORPHANED in dataset:  {cfg_summary['orphaned_in_dataset']}")

    # List missing messages
    if report["messages"]["missing"]:
        print(f"\n--- Missing Messages ({len(report['messages']['missing'])}) ---")
        for msg, details in sorted(report["messages"]["missing"].items()):
            print(f"  {msg} (in {details['manual_count']} manuals)")

    # List orphaned messages
    if report["messages"]["orphaned"]:
        print(f"\n--- Orphaned Messages ({len(report['messages']['orphaned'])}) ---")
        for msg in report["messages"]["orphaned"]:
            print(f"  {msg}")

    if not args.no_save:
        save_report(report)

    # Return non-zero if there are gaps
    if msg_summary["missing_from_dataset"] > 0 or cfg_summary["missing_from_dataset"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
