#!/usr/bin/env python3
"""Stage 2: Voting and preliminary structure determination for workflow v2.

Reads extractions from conversation store and applies majority voting
to determine preliminary canonical structures for each message.

Usage:
    uv run python scripts/vote_preliminary_v2.py --conv-dir _working/stage1_extractions
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Add src to path for validation imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.validation import (
    VotingConfig,
)
from src.validation.fingerprint import compute_message_fingerprint, compute_message_fingerprint_detailed
from src.validation.version_detect import get_protocol_version


@dataclass
class ExtractionRecord:
    """An extraction from a specific manual."""
    manual: str
    message_name: str
    structure: dict
    fingerprint: str
    fingerprint_detailed: dict
    protocol_version: int


@dataclass
class PreliminaryResult:
    """Result of preliminary voting for a message."""
    message_name: str
    protocol_version: int
    
    # Status
    status: str  # "unanimous", "majority", "split", "single_source"
    agreement_ratio: float
    
    # Winning structure
    winning_structure: dict
    winning_fingerprint: str
    agreeing_sources: list[str]
    
    # All extractions (for Stage 3 context)
    all_extractions: list[dict]  # [{source, structure, fingerprint}]
    
    # Disagreeing sources (if any)
    disagreeing_sources: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "message_name": self.message_name,
            "protocol_version": self.protocol_version,
            "status": self.status,
            "agreement_ratio": self.agreement_ratio,
            "winning_structure": self.winning_structure,
            "winning_fingerprint": self.winning_fingerprint,
            "agreeing_sources": self.agreeing_sources,
            "disagreeing_sources": self.disagreeing_sources,
            "all_extractions": self.all_extractions,
        }


def load_extractions_from_conversations(conv_dir: Path) -> list[ExtractionRecord]:
    """Load all extractions from conversation store."""
    
    records = []
    
    for manual_dir in conv_dir.iterdir():
        if not manual_dir.is_dir():
            continue
        
        manual_name = manual_dir.name
        
        for conv_file in manual_dir.glob("*.json"):
            try:
                with open(conv_file) as f:
                    data = json.load(f)
                
                structure = data.get("extracted_structure")
                if not structure or "error" in structure:
                    continue
                
                message_name = data.get("message_name", "")
                if not message_name:
                    continue
                
                # Compute fingerprint
                fp = compute_message_fingerprint(structure)
                fp_detailed = compute_message_fingerprint_detailed(structure)
                
                # Detect protocol version
                version = get_protocol_version(structure)
                
                records.append(ExtractionRecord(
                    manual=manual_name,
                    message_name=message_name,
                    structure=structure,
                    fingerprint=fp,
                    fingerprint_detailed=fp_detailed,
                    protocol_version=version,
                ))
                
            except (json.JSONDecodeError, KeyError) as e:
                print(f"  Warning: Failed to load {conv_file}: {e}")
    
    return records


def group_by_message_and_version(
    records: list[ExtractionRecord],
) -> dict[tuple[str, int], list[ExtractionRecord]]:
    """Group extractions by (message_name, protocol_version)."""
    
    groups: dict[tuple[str, int], list[ExtractionRecord]] = defaultdict(list)
    
    for record in records:
        key = (record.message_name, record.protocol_version)
        groups[key].append(record)
    
    return dict(groups)


def vote_on_group(
    records: list[ExtractionRecord],
    config: VotingConfig,
) -> PreliminaryResult:
    """Vote on a group of extractions for the same message/version."""
    
    if not records:
        raise ValueError("Empty record list")
    
    message_name = records[0].message_name
    protocol_version = records[0].protocol_version
    
    # Count fingerprints
    fingerprint_counts: dict[str, int] = defaultdict(int)
    fingerprint_to_records: dict[str, list[ExtractionRecord]] = defaultdict(list)
    
    for record in records:
        fingerprint_counts[record.fingerprint] += 1
        fingerprint_to_records[record.fingerprint].append(record)
    
    total = len(records)
    
    # Find winner
    winning_fingerprint = max(fingerprint_counts.keys(), key=lambda fp: fingerprint_counts[fp])
    agreement_count = fingerprint_counts[winning_fingerprint]
    agreement_ratio = agreement_count / total
    
    # Determine status
    if total == 1:
        status = "single_source"
    elif agreement_ratio == 1.0:
        status = "unanimous"
    elif agreement_ratio >= config.threshold:
        status = "majority"
    else:
        status = "split"
    
    # Get winning structure (first one with winning fingerprint)
    winning_records = fingerprint_to_records[winning_fingerprint]
    winning_structure = winning_records[0].structure
    
    # Collect sources
    agreeing_sources = [r.manual for r in winning_records]
    disagreeing_sources = [r.manual for r in records if r.fingerprint != winning_fingerprint]
    
    # Build all extractions list for Stage 3 context
    all_extractions = [
        {
            "source": r.manual,
            "structure": r.structure,
            "fingerprint": r.fingerprint,
        }
        for r in records
    ]
    
    return PreliminaryResult(
        message_name=message_name,
        protocol_version=protocol_version,
        status=status,
        agreement_ratio=agreement_ratio,
        winning_structure=winning_structure,
        winning_fingerprint=winning_fingerprint,
        agreeing_sources=agreeing_sources,
        disagreeing_sources=disagreeing_sources,
        all_extractions=all_extractions,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Stage 2: Preliminary voting for workflow v2"
    )
    parser.add_argument(
        "--conv-dir",
        type=Path,
        default=Path("_working/stage1_extractions"),
        help="Directory containing conversation records",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("_working/stage2_voting"),
        help="Output directory for preliminary structures",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.75,
        help="Voting threshold for majority (default: 0.75)",
    )
    parser.add_argument(
        "--message",
        type=str,
        help="Process single message only",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing files",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )
    
    args = parser.parse_args()
    
    if not args.conv_dir.exists():
        print(f"Error: Conversation directory not found: {args.conv_dir}")
        return 1
    
    config = VotingConfig(threshold=args.threshold)
    
    print(f"Loading extractions from: {args.conv_dir}")
    
    # Load all extractions
    records = load_extractions_from_conversations(args.conv_dir)
    print(f"Loaded {len(records)} extractions")
    
    if not records:
        print("No extractions found")
        return 1
    
    # Group by message and version
    groups = group_by_message_and_version(records)
    print(f"Grouped into {len(groups)} message/version combinations")
    
    # Filter to single message if requested
    if args.message:
        groups = {k: v for k, v in groups.items() if k[0] == args.message}
        if not groups:
            print(f"Error: Message '{args.message}' not found")
            return 1
    
    # Vote on each group
    results: list[PreliminaryResult] = []
    status_counts = defaultdict(int)
    
    for (msg_name, version), group_records in sorted(groups.items()):
        result = vote_on_group(group_records, config)
        results.append(result)
        status_counts[result.status] += 1
        
        if args.verbose:
            sources = len(result.all_extractions)
            print(f"  {msg_name} v{version}: {result.status} ({result.agreement_ratio:.0%}, {sources} sources)")
    
    # Summary
    print(f"\n=== Voting Summary ===")
    print(f"  Unanimous: {status_counts['unanimous']}")
    print(f"  Majority:  {status_counts['majority']}")
    print(f"  Split:     {status_counts['split']}")
    print(f"  Single:    {status_counts['single_source']}")
    
    if args.dry_run:
        print("\n[Dry run - not writing files]")
        return 0
    
    # Write preliminary structures
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    # Write per-message files (for Stage 3)
    by_version_dir = args.output_dir / "by_version"
    by_version_dir.mkdir(exist_ok=True)
    
    for result in results:
        # Filename includes version
        safe_name = result.message_name.replace("-", "_")
        filename = f"{safe_name}_v{result.protocol_version}.json"
        
        output_path = by_version_dir / filename
        with open(output_path, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
    
    print(f"\nWrote {len(results)} preliminary structures to: {by_version_dir}")
    
    # Write summary report
    summary = {
        "total_messages": len(results),
        "status_counts": dict(status_counts),
        "needs_enhanced_review": [
            {"message": r.message_name, "version": r.protocol_version, "ratio": r.agreement_ratio}
            for r in results
            if r.status == "split"
        ],
        "results": [
            {
                "message": r.message_name,
                "version": r.protocol_version,
                "status": r.status,
                "agreement_ratio": r.agreement_ratio,
                "sources": len(r.all_extractions),
            }
            for r in results
        ],
    }
    
    summary_path = args.output_dir / "voting_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    
    print(f"Wrote summary to: {summary_path}")
    
    # Highlight messages needing enhanced review
    needs_review = [r for r in results if r.status == "split"]
    if needs_review:
        print(f"\n⚠️  {len(needs_review)} messages need enhanced Stage 3 review:")
        for r in needs_review[:10]:
            print(f"    {r.message_name} v{r.protocol_version}: {r.agreement_ratio:.0%} agreement")
        if len(needs_review) > 10:
            print(f"    ... and {len(needs_review) - 10} more")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
