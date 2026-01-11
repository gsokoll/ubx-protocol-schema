#!/usr/bin/env python3
"""
Re-extract messages that have structural validation issues.

Identifies messages with payload length, field, or type mismatches
and re-extracts them from PDFs.

Usage:
    uv run python validation/scripts/reextract_issues.py --list
    uv run python validation/scripts/reextract_issues.py --class CFG
    uv run python validation/scripts/reextract_issues.py --all
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from validation.scripts.extract_missing import (
    extract_missing_message,
    save_extraction,
    load_inventory,
)


STRUCTURAL_KEYWORDS = [
    "offset", "type", "length", "missing", "extra",
    "size", "count", "byte", "payload", "bitfield"
]


def find_messages_with_structural_issues() -> list[str]:
    """Find messages that have structural validation issues."""
    reports_dir = PROJECT_ROOT / "validation" / "reports"

    messages_with_issues = []

    for report_file in reports_dir.glob("*_validation.json"):
        with open(report_file) as f:
            report = json.load(f)

        msg_name = report.get("message", "")

        has_structural = False
        for result in report.get("results", []):
            if result.get("matches") is False:
                for disc in result.get("discrepancies", []):
                    issue = disc.get("issue", "").lower()
                    if any(kw in issue for kw in STRUCTURAL_KEYWORDS):
                        has_structural = True
                        break
                if has_structural:
                    break

        if has_structural:
            messages_with_issues.append(msg_name)

    return sorted(messages_with_issues)


def list_issues():
    """List all messages with structural issues."""
    messages = find_messages_with_structural_issues()

    # Group by class
    by_class = {}
    for msg in messages:
        parts = msg.split("-")
        if len(parts) >= 2:
            cls = parts[1]
            if cls not in by_class:
                by_class[cls] = []
            by_class[cls].append(msg)

    print(f"Messages with structural issues ({len(messages)} total):\n")
    for cls, msgs in sorted(by_class.items()):
        print(f"{cls} ({len(msgs)}):")
        for msg in sorted(msgs):
            print(f"  {msg}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Re-extract messages with structural issues"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List messages with structural issues"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Re-extract all messages with structural issues"
    )
    parser.add_argument(
        "--class",
        dest="msg_class",
        help="Re-extract all messages of a class (e.g., CFG)"
    )
    parser.add_argument(
        "message",
        nargs="?",
        help="Re-extract a specific message"
    )

    args = parser.parse_args()

    if args.list:
        list_issues()
        return 0

    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set")
        return 1

    # Get messages to re-extract
    all_issues = find_messages_with_structural_issues()
    inventory = load_inventory()

    messages_to_extract = []

    if args.all:
        messages_to_extract = all_issues
    elif args.msg_class:
        messages_to_extract = [
            m for m in all_issues
            if m.split("-")[1] == args.msg_class
        ]
    elif args.message:
        if args.message in all_issues:
            messages_to_extract = [args.message]
        else:
            print(f"Error: {args.message} not in issues list")
            return 1
    else:
        parser.print_help()
        return 1

    print(f"Re-extracting {len(messages_to_extract)} messages...\n")

    output_dir = PROJECT_ROOT / "data" / "preliminary" / "reextracted_fixes"

    success_count = 0
    for i, msg_name in enumerate(messages_to_extract, 1):
        print(f"[{i}/{len(messages_to_extract)}] {msg_name}")

        extracted = extract_missing_message(msg_name, inventory)

        if extracted:
            save_extraction(extracted, output_dir)
            success_count += 1

        # Rate limiting
        time.sleep(1)

    print(f"\n=== Summary ===")
    print(f"Re-extracted: {success_count}/{len(messages_to_extract)}")
    print(f"Output dir: {output_dir}")

    return 0 if success_count == len(messages_to_extract) else 1


if __name__ == "__main__":
    sys.exit(main())
