#!/usr/bin/env python3
"""Majority-voting validation pipeline for UBX message extractions.

This script implements the full validation pipeline:
1. Load all extractions from data/ubx/by-manual/
2. Group by (message_name, protocol_version)
3. Compute structural fingerprints
4. Vote on canonical definition via majority rules
5. Generate reports and canonical output

Usage:
    python scripts/validate_majority.py [--extractions-dir DIR] [--output-dir DIR]
    python scripts/validate_majority.py --message UBX-NAV-PVT  # Single message test
"""

import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.validation import (
    group_extractions,
    get_group_summary,
    vote_on_all_groups,
    VotingConfig,
    generate_validation_report,
    generate_discrepancy_report,
    print_summary,
    write_canonical_messages,
)


def main():
    parser = argparse.ArgumentParser(
        description="Majority-voting validation for UBX message extractions"
    )
    parser.add_argument(
        "--extractions-dir",
        type=Path,
        default=Path("data/ubx/by-manual"),
        help="Directory containing *_anthropic.json extraction files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/ubx/validated"),
        help="Output directory for validated canonical files",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=Path("analysis_reports"),
        help="Directory for validation reports",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.75,
        help="Voting threshold for consensus (default: 0.75)",
    )
    parser.add_argument(
        "--min-sources",
        type=int,
        default=3,
        help="Minimum sources for high confidence (default: 3)",
    )
    parser.add_argument(
        "--message",
        type=str,
        help="Filter to single message name (e.g., UBX-NAV-PVT) for testing",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run validation but don't write output files",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )
    
    args = parser.parse_args()
    
    # Validate inputs
    if not args.extractions_dir.exists():
        print(f"Error: Extractions directory not found: {args.extractions_dir}")
        return 1
    
    # Configure voting
    config = VotingConfig(
        threshold=args.threshold,
        min_sources=args.min_sources,
    )
    
    print(f"Loading extractions from: {args.extractions_dir}")
    print(f"Voting threshold: {config.threshold:.0%}")
    print(f"Min sources for high confidence: {config.min_sources}")
    
    # Step 1: Group extractions
    print("\n--- Step 1: Grouping extractions ---")
    groups = group_extractions(args.extractions_dir)
    
    # Filter to single message if requested
    if args.message:
        filtered = {
            k: v for k, v in groups.items()
            if k[0] == args.message
        }
        if not filtered:
            print(f"Error: Message '{args.message}' not found in extractions")
            print(f"Available messages (first 20):")
            for name, _ in sorted(set((k[0], None) for k in groups.keys()))[:20]:
                print(f"  {name}")
            return 1
        groups = filtered
        print(f"Filtered to message: {args.message}")
    
    # Print grouping summary
    summary = get_group_summary(groups)
    print(f"\nGrouped {summary['total_message_instances']} message instances into {summary['total_groups']} groups")
    print(f"By protocol version: {summary['by_protocol_version']}")
    
    if args.verbose:
        print("\nSample groups:")
        for i, ((name, version), group) in enumerate(sorted(groups.items())[:5]):
            print(f"  {name} v{version}: {group.source_count} sources, {group.unique_fingerprints} unique fingerprints")
    
    # Step 2: Vote on all groups
    print("\n--- Step 2: Voting on message definitions ---")
    results = vote_on_all_groups(groups, config)
    
    # Print summary
    print_summary(results)
    
    if args.dry_run:
        print("\n[Dry run - not writing output files]")
        return 0
    
    # Step 3: Generate reports
    print("\n--- Step 3: Generating reports ---")
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    
    validation_report = generate_validation_report(
        results,
        output_path=args.reports_dir / "validation_report.json",
    )
    print(f"Wrote: {args.reports_dir / 'validation_report.json'}")
    
    discrepancy_report = generate_discrepancy_report(
        results,
        output_path=args.reports_dir / "discrepancy_report.json",
    )
    print(f"Wrote: {args.reports_dir / 'discrepancy_report.json'}")
    print(f"  - {discrepancy_report['summary']['total_messages_with_issues']} messages with issues")
    print(f"  - {discrepancy_report['summary']['total_outliers']} total outliers")
    
    # Step 4: Write canonical output
    print("\n--- Step 4: Writing canonical output ---")
    manifest = write_canonical_messages(
        results,
        output_dir=args.output_dir,
        require_consensus=True,
        min_confidence="low",  # Include low confidence for review
    )
    
    print(f"Wrote {manifest['stats']['written']} canonical message files to: {args.output_dir}")
    print(f"  - Skipped (no consensus): {manifest['stats']['skipped_no_consensus']}")
    print(f"  - Skipped (low confidence): {manifest['stats']['skipped_low_confidence']}")
    
    print("\n✓ Validation complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
