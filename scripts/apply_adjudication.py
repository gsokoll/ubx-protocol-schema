#!/usr/bin/env python3
"""Apply adjudication decisions to unified config keys.

Reads decisions from adjudication_queue.json and applies them to
unified_config_keys.json, updating the specified fields.

Usage:
    uv run python scripts/apply_adjudication.py --dry-run
    uv run python scripts/apply_adjudication.py --apply
"""

import argparse
import json
import sys
from pathlib import Path


def apply_adjudication(
    queue_file: Path,
    unified_file: Path,
    dry_run: bool = True,
) -> int:
    """Apply adjudication decisions to unified config keys."""

    # Load files
    queue_data = json.loads(queue_file.read_text())
    unified_data = json.loads(unified_file.read_text())

    items = queue_data.get("items", [])
    keys = unified_data.get("keys", [])

    # Build key lookup by key_id
    key_by_id = {k["key_id"]: k for k in keys}

    # Filter to items with decisions
    decided = [item for item in items if item.get("decision") is not None]

    print(f"Adjudication queue: {len(items)} items, {len(decided)} with decisions")
    print(f"Unified config keys: {len(keys)} keys")
    print()

    if not decided:
        print("No decisions to apply!")
        return 0

    # Apply decisions
    changes = []
    not_found = []

    for item in decided:
        key_id = item["key_id"]
        field = item["field"]
        new_value = item["decision"]
        key_name = item["key_name"]
        reasoning = item.get("llm_reasoning", "")

        if key_id not in key_by_id:
            not_found.append(item)
            continue

        key = key_by_id[key_id]
        old_value = key.get(field)

        # Skip if already matches
        if old_value == new_value:
            print(f"  SKIP {key_name}.{field}: already {new_value!r}")
            continue

        changes.append({
            "key_id": key_id,
            "key_name": key_name,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "reasoning": reasoning,
        })

        if not dry_run:
            key[field] = new_value

    # Report
    print(f"\n=== Changes {'(dry-run)' if dry_run else ''} ===")
    for change in changes:
        print(f"  {change['key_name']}.{change['field']}:")
        print(f"    {change['old_value']!r} -> {change['new_value']!r}")
        if change['reasoning']:
            print(f"    Reason: {change['reasoning']}")

    if not_found:
        print(f"\n=== Not found in unified ({len(not_found)}) ===")
        for item in not_found:
            print(f"  {item['key_name']} ({item['key_id']})")

    print(f"\n=== Summary ===")
    print(f"  Changes to apply: {len(changes)}")
    print(f"  Keys not found: {len(not_found)}")

    if dry_run:
        print(f"\n  Use --apply to write changes to {unified_file}")
        return 0

    # Write updated unified file
    unified_file.write_text(json.dumps(unified_data, indent=2))
    print(f"\n  Written to: {unified_file}")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Apply adjudication decisions to unified config keys")
    parser.add_argument("--queue", type=Path, default=Path("data/config_keys/adjudication_queue.json"),
                        help="Adjudication queue file")
    parser.add_argument("--unified", type=Path, default=Path("data/config_keys/unified_config_keys.json"),
                        help="Unified config keys file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without applying")
    parser.add_argument("--apply", action="store_true",
                        help="Apply changes to unified file")

    args = parser.parse_args()

    if not args.apply and not args.dry_run:
        print("Error: Must specify --dry-run or --apply")
        return 1

    dry_run = not args.apply

    return apply_adjudication(
        queue_file=args.queue,
        unified_file=args.unified,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
