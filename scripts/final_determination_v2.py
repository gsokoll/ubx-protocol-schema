#!/usr/bin/env python3
"""Stage 4: Final automated determination for workflow v2.

Reads post-review conversations and makes final decisions on message structures.
Generates canonical output and manual adjudication reports for unresolved cases.

Usage:
    uv run python scripts/final_determination_v2.py --conv-dir _working/stage1_extractions --preliminary-dir _working/stage2_voting
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.validation.fingerprint import compute_message_fingerprint


@dataclass
class ReviewedExtraction:
    """An extraction with its review result."""
    manual: str
    message_name: str
    protocol_version: int
    original_structure: dict
    review: dict | None
    
    @property
    def verdict(self) -> str:
        if not self.review:
            return "not_reviewed"
        return self.review.get("verdict", "unknown")
    
    @property
    def confidence(self) -> str:
        if not self.review:
            return "unknown"
        return self.review.get("confidence", "unknown")
    
    @property
    def corrected_structure(self) -> dict | None:
        if not self.review:
            return None
        return self.review.get("corrected_structure")
    
    @property
    def final_structure(self) -> dict:
        """Get the final structure (corrected if available, else original)."""
        struct = self.corrected_structure if self.corrected_structure else self.original_structure
        # Handle list responses from LLM
        if isinstance(struct, list):
            struct = struct[0] if struct else {}
        return struct if isinstance(struct, dict) else {}


@dataclass
class FinalResult:
    """Final determination for a message."""
    message_name: str
    protocol_version: int
    
    # Decision
    decision: str  # "accepted", "accepted_with_corrections", "valid_variations", "needs_manual_review"
    confidence: str  # "high", "medium", "low"
    
    # Final structure(s)
    final_structure: dict | None
    variations: list[dict] = field(default_factory=list)  # For valid_variations
    
    # Supporting info
    agreeing_sources: list[str] = field(default_factory=list)
    review_summary: dict = field(default_factory=dict)
    
    # For manual review
    unresolved_issues: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "message_name": self.message_name,
            "protocol_version": self.protocol_version,
            "decision": self.decision,
            "confidence": self.confidence,
            "final_structure": self.final_structure,
            "variations": self.variations,
            "agreeing_sources": self.agreeing_sources,
            "review_summary": self.review_summary,
            "unresolved_issues": self.unresolved_issues,
        }


def load_reviewed_extractions(conv_dir: Path) -> list[ReviewedExtraction]:
    """Load all reviewed extractions from conversation store."""
    
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
                
                # Detect protocol version (simplified)
                version = 0
                
                records.append(ReviewedExtraction(
                    manual=manual_name,
                    message_name=message_name,
                    protocol_version=version,
                    original_structure=structure,
                    review=data.get("review"),
                ))
                
            except (json.JSONDecodeError, KeyError) as e:
                print(f"  Warning: Failed to load {conv_file}: {e}")
    
    return records


def determine_final(
    records: list[ReviewedExtraction],
) -> FinalResult:
    """Make final determination for a group of reviewed extractions."""
    
    if not records:
        raise ValueError("Empty record list")
    
    message_name = records[0].message_name
    protocol_version = records[0].protocol_version
    
    # Categorize by verdict
    by_verdict = defaultdict(list)
    for r in records:
        by_verdict[r.verdict].append(r)
    
    # Count final structures
    structure_fingerprints = defaultdict(list)
    for r in records:
        fp = compute_message_fingerprint(r.final_structure)
        structure_fingerprints[fp].append(r)
    
    # Build review summary
    review_summary = {
        "total_sources": len(records),
        "reviewed": len([r for r in records if r.review]),
        "by_verdict": {k: len(v) for k, v in by_verdict.items()},
        "unique_structures": len(structure_fingerprints),
    }
    
    # Decision logic
    total = len(records)
    
    # Case 1: All agree (after corrections)
    if len(structure_fingerprints) == 1:
        fp = list(structure_fingerprints.keys())[0]
        agreeing = structure_fingerprints[fp]
        
        has_corrections = any(r.verdict == "extraction_error" for r in agreeing)
        
        return FinalResult(
            message_name=message_name,
            protocol_version=protocol_version,
            decision="accepted_with_corrections" if has_corrections else "accepted",
            confidence="high" if len(agreeing) >= 3 else "medium",
            final_structure=agreeing[0].final_structure,
            agreeing_sources=[r.manual for r in agreeing],
            review_summary=review_summary,
        )
    
    # Case 2: Valid variations (different manuals have documented differences)
    valid_change_records = by_verdict.get("valid_change", [])
    version_bump_records = by_verdict.get("version_bump", [])
    
    if valid_change_records or version_bump_records:
        # Collect distinct variations
        variations = []
        seen_fps = set()
        
        for r in records:
            fp = compute_message_fingerprint(r.final_structure)
            if fp not in seen_fps:
                seen_fps.add(fp)
                variations.append({
                    "structure": r.final_structure,
                    "sources": [rec.manual for rec in records 
                               if compute_message_fingerprint(rec.final_structure) == fp],
                    "verdict": r.verdict,
                })
        
        return FinalResult(
            message_name=message_name,
            protocol_version=protocol_version,
            decision="valid_variations",
            confidence="medium",
            final_structure=None,
            variations=variations,
            review_summary=review_summary,
        )
    
    # Case 3: Majority after corrections
    # Find most common final structure
    most_common_fp = max(structure_fingerprints.keys(), 
                         key=lambda fp: len(structure_fingerprints[fp]))
    agreeing = structure_fingerprints[most_common_fp]
    agreement_ratio = len(agreeing) / total
    
    if agreement_ratio >= 0.75:
        return FinalResult(
            message_name=message_name,
            protocol_version=protocol_version,
            decision="accepted_with_corrections",
            confidence="medium" if agreement_ratio >= 0.9 else "low",
            final_structure=agreeing[0].final_structure,
            agreeing_sources=[r.manual for r in agreeing],
            review_summary=review_summary,
        )
    
    # Case 4: No resolution - needs manual review
    issues = []
    for fp, recs in structure_fingerprints.items():
        sources = [r.manual for r in recs]
        verdicts = set(r.verdict for r in recs)
        issues.append(f"Structure variant: {sources} ({verdicts})")
    
    # Check for low confidence reviews
    low_conf = [r for r in records if r.confidence == "low"]
    if low_conf:
        issues.append(f"Low confidence reviews: {[r.manual for r in low_conf]}")
    
    return FinalResult(
        message_name=message_name,
        protocol_version=protocol_version,
        decision="needs_manual_review",
        confidence="low",
        final_structure=None,
        review_summary=review_summary,
        unresolved_issues=issues,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Stage 4: Final automated determination for workflow v2"
    )
    parser.add_argument(
        "--conv-dir",
        type=Path,
        default=Path("_working/stage1_extractions"),
        help="Directory containing conversation records with reviews",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/final"),
        help="Output directory for final structures",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=Path("analysis_reports/v2"),
        help="Directory for reports",
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
    
    print(f"Loading reviewed extractions from: {args.conv_dir}")
    
    # Load all reviewed extractions
    records = load_reviewed_extractions(args.conv_dir)
    print(f"Loaded {len(records)} extractions")
    
    reviewed = [r for r in records if r.review]
    print(f"  With reviews: {len(reviewed)}")
    
    if not records:
        print("No extractions found")
        return 1
    
    # Group by message and version
    groups: dict[tuple[str, int], list[ReviewedExtraction]] = defaultdict(list)
    for r in records:
        groups[(r.message_name, r.protocol_version)].append(r)
    
    print(f"Grouped into {len(groups)} message/version combinations")
    
    # Filter to single message if requested
    if args.message:
        groups = {k: v for k, v in groups.items() if k[0] == args.message}
        if not groups:
            print(f"Error: Message '{args.message}' not found")
            return 1
    
    # Make final determination for each group
    results: list[FinalResult] = []
    decision_counts = defaultdict(int)
    
    for (msg_name, version), group_records in sorted(groups.items()):
        result = determine_final(group_records)
        results.append(result)
        decision_counts[result.decision] += 1
        
        if args.verbose:
            print(f"  {msg_name} v{version}: {result.decision} ({result.confidence})")
    
    # Summary
    print(f"\n=== Final Determination Summary ===")
    print(f"  Accepted:              {decision_counts['accepted']}")
    print(f"  Accepted (corrected):  {decision_counts['accepted_with_corrections']}")
    print(f"  Valid variations:      {decision_counts['valid_variations']}")
    print(f"  Needs manual review:   {decision_counts['needs_manual_review']}")
    
    if args.dry_run:
        print("\n[Dry run - not writing files]")
        return 0
    
    # Write outputs
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    
    # Write canonical messages (accepted only)
    canonical_dir = args.output_dir / "canonical"
    canonical_dir.mkdir(exist_ok=True)
    
    canonical_count = 0
    for result in results:
        if result.decision in ("accepted", "accepted_with_corrections") and result.final_structure:
            safe_name = result.message_name.replace("-", "_")
            out_path = canonical_dir / f"{safe_name}.json"
            
            output = {
                "message": result.final_structure,
                "metadata": {
                    "decision": result.decision,
                    "confidence": result.confidence,
                    "sources": result.agreeing_sources,
                    "review_summary": result.review_summary,
                },
            }
            
            with open(out_path, "w") as f:
                json.dump(output, f, indent=2)
            
            canonical_count += 1
    
    print(f"\nWrote {canonical_count} canonical messages to: {canonical_dir}")
    
    # Generate manual adjudication report
    needs_review = [r for r in results if r.decision == "needs_manual_review"]
    
    if needs_review:
        report = {
            "generated": datetime.now().isoformat(),
            "total_messages": len(results),
            "needs_manual_review": len(needs_review),
            "messages": [r.to_dict() for r in needs_review],
        }
        
        report_path = args.reports_dir / "manual_adjudication_required.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        
        print(f"\n⚠️  {len(needs_review)} messages need manual adjudication")
        print(f"   Report: {report_path}")
        
        for r in needs_review[:5]:
            print(f"   - {r.message_name} v{r.protocol_version}")
            for issue in r.unresolved_issues[:2]:
                print(f"       {issue}")
        if len(needs_review) > 5:
            print(f"   ... and {len(needs_review) - 5} more")
    else:
        print("\n✓ All messages resolved automatically - no manual adjudication needed!")
    
    # Write full summary
    summary = {
        "generated": datetime.now().isoformat(),
        "total_messages": len(results),
        "decision_counts": dict(decision_counts),
        "results": [r.to_dict() for r in results],
    }
    
    summary_path = args.reports_dir / "final_determination_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    
    print(f"\nWrote summary to: {summary_path}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
