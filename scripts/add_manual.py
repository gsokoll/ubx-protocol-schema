#!/usr/bin/env python3
"""Orchestrator for adding new u-blox interface manuals.

Automates the workflow for adding a new PDF manual:
1. Build inventory (scan PDFs for messages)
2. Gap analysis (compare inventory vs schema)
3. Extract missing messages (from PDFs using LLM)
4. Merge into schema
5. (Optional) Extract config keys
6. (Optional) Fix missing bitfields
7. Generate coverage report

Usage:
    # Add a new manual and extract any new messages
    uv run python scripts/add_manual.py --pdf-path interface_manuals/new-device/manual.pdf

    # Full workflow including config keys and bitfields
    uv run python scripts/add_manual.py --pdf-path manual.pdf --extract-config-keys --fix-bitfields

    # Dry-run to see what would be extracted
    uv run python scripts/add_manual.py --dry-run

    # Skip extraction (just update inventory and gap analysis)
    uv run python scripts/add_manual.py --skip-extract

    # Process all PDFs (rebuild inventory)
    uv run python scripts/add_manual.py --all

Related workflows:
    - Config keys: See docs/config-key-extraction-workflow.md
    - Bitfields: See docs/bitfield-extraction-workflow.md
    - Enumerations: See docs/enumeration-extraction-workflow.md
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def run_script(script_path: str, args: list[str] = None, description: str = "") -> bool:
    """Run a Python script and return success status."""
    args = args or []
    full_path = PROJECT_ROOT / script_path

    print(f"\n{'='*60}")
    print(f"Step: {description}")
    print(f"Running: uv run python {script_path} {' '.join(args)}")
    print('='*60)

    result = subprocess.run(
        ["uv", "run", "python", str(full_path)] + args,
        cwd=PROJECT_ROOT,
    )

    if result.returncode != 0:
        print(f"\n[ERROR] Step failed: {description}")
        return False

    print(f"\n[OK] {description} completed")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Orchestrator for adding new u-blox interface manuals"
    )
    parser.add_argument(
        "--pdf-path",
        type=Path,
        help="Path to the new PDF manual (relative to project root)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help="Skip extraction step (just update inventory and gap analysis)",
    )
    parser.add_argument(
        "--skip-merge",
        action="store_true",
        help="Skip merge step (extract but don't update schema)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all PDFs (rebuild full inventory)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--extract-config-keys",
        action="store_true",
        help="Also extract config keys from the manual (requires GOOGLE_API_KEY)",
    )
    parser.add_argument(
        "--fix-bitfields",
        action="store_true",
        help="Fix missing bitfields after extraction (requires GOOGLE_API_KEY)",
    )

    args = parser.parse_args()

    # Validate PDF path if provided
    if args.pdf_path:
        full_path = PROJECT_ROOT / args.pdf_path
        if not full_path.exists():
            print(f"Error: PDF not found: {full_path}")
            sys.exit(1)
        print(f"Processing new manual: {args.pdf_path}")
    elif not args.all and not args.dry_run:
        print("Note: No --pdf-path specified, will scan all existing PDFs")

    print("\n" + "="*60)
    print("UBX Manual Integration Workflow")
    print("="*60)

    # Step 1: Build inventory
    inventory_args = []
    if args.verbose:
        inventory_args.append("--verbose")

    if not run_script(
        "validation/scripts/build_inventory.py",
        inventory_args,
        "Build message inventory from PDFs"
    ):
        sys.exit(1)

    # Step 2: Gap analysis
    gap_args = []
    if args.verbose:
        gap_args.append("--verbose")

    if not run_script(
        "validation/scripts/gap_analysis.py",
        gap_args,
        "Analyze gaps between inventory and schema"
    ):
        sys.exit(1)

    # Step 3: List missing messages
    if not run_script(
        "validation/scripts/extract_missing.py",
        ["--list"],
        "List missing messages"
    ):
        sys.exit(1)

    if args.dry_run:
        print("\n" + "="*60)
        print("[DRY RUN] Would extract missing messages and merge into schema")
        print("="*60)
        sys.exit(0)

    if args.skip_extract:
        print("\n" + "="*60)
        print("[SKIP] Extraction skipped (--skip-extract)")
        print("="*60)
    else:
        # Step 4: Extract missing messages
        if not run_script(
            "validation/scripts/extract_missing.py",
            ["--all"],
            "Extract missing messages from PDFs"
        ):
            print("\n[WARNING] Extraction had issues, continuing...")

    if args.skip_merge:
        print("\n" + "="*60)
        print("[SKIP] Merge skipped (--skip-merge)")
        print("="*60)
    else:
        # Step 5: Preview merge
        if not run_script(
            "validation/scripts/merge_extracted.py",
            ["--dry-run"],
            "Preview merge changes"
        ):
            sys.exit(1)

        # Step 6: Apply merge
        if not run_script(
            "validation/scripts/merge_extracted.py",
            [],
            "Merge extracted messages into schema"
        ):
            sys.exit(1)

    # Optional Step: Extract config keys
    if args.extract_config_keys:
        if not args.pdf_path:
            print("\n[WARNING] --extract-config-keys requires --pdf-path, skipping")
        else:
            config_args = ["--pdf-path", str(args.pdf_path)]
            if not run_script(
                "scripts/bulk_extraction/extract_config_keys_with_gemini.py",
                config_args,
                "Extract config keys from manual"
            ):
                print("\n[WARNING] Config key extraction had issues, continuing...")
            else:
                # Run conflict detection and merge
                run_script(
                    "scripts/detect_config_key_conflicts.py",
                    [],
                    "Detect config key conflicts"
                )
                run_script(
                    "scripts/merge_config_keys.py",
                    [],
                    "Merge config keys"
                )

    # Optional Step: Fix missing bitfields
    if args.fix_bitfields:
        bitfield_args = ["--fix-bitfields"]
        if args.dry_run:
            bitfield_args.append("--dry-run")
        if not run_script(
            "validation/scripts/validate_all_messages.py",
            bitfield_args,
            "Fix missing bitfields"
        ):
            print("\n[WARNING] Bitfield extraction had issues, continuing...")

    # Final Step: Generate coverage report
    if not run_script(
        "scripts/generate_coverage_report.py",
        [],
        "Generate coverage report"
    ):
        sys.exit(1)

    # Summary
    print("\n" + "="*60)
    print("WORKFLOW COMPLETE")
    print("="*60)
    print("\nNext steps:")
    print("1. Review changes: git diff data/messages/ubx_messages.json")
    print("2. Run tests: uv run pytest testing/tests/ -v")
    print("3. Cross-validate: uv run python validation/scripts/cross_validate.py --summary")
    print("4. Commit changes if satisfied")

    if not args.extract_config_keys:
        print("\nOptional: Extract config keys with --extract-config-keys")
        print("         See docs/config-key-extraction-workflow.md")
    if not args.fix_bitfields:
        print("\nOptional: Fix bitfields with --fix-bitfields")
        print("         See docs/bitfield-extraction-workflow.md")
    print("\nEnumerations are typically stable. Validate manually if needed:")
    print("         See docs/enumeration-extraction-workflow.md")


if __name__ == "__main__":
    main()
