"""Report generation for validation results.

Generates machine-readable JSON reports and human-readable summaries
of the voting/validation process.
"""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .voting import ConsensusResult, Outlier
from .grouping import MessageGroup


def generate_validation_report(
    results: dict[tuple[str, int], ConsensusResult],
    output_path: Path | None = None,
) -> dict:
    """Generate comprehensive validation report.
    
    Args:
        results: Voting results from vote_on_all_groups
        output_path: Optional path to write JSON report
    
    Returns:
        Report dict
    """
    report = {
        'generated_at': datetime.now().isoformat(),
        'summary': _generate_summary(results),
        'by_confidence': _group_by_confidence(results),
        'messages': _serialize_results(results),
        'outliers': _collect_outliers(results),
    }
    
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
    
    return report


def _generate_summary(results: dict[tuple[str, int], ConsensusResult]) -> dict:
    """Generate summary statistics."""
    total = len(results)
    
    consensus_count = sum(1 for r in results.values() if r.has_consensus)
    no_consensus_count = total - consensus_count
    
    by_confidence = {}
    for r in results.values():
        by_confidence[r.confidence] = by_confidence.get(r.confidence, 0) + 1
    
    total_outliers = sum(len(r.outliers) for r in results.values())
    
    avg_confidence = 0.0
    if total > 0:
        avg_confidence = sum(r.confidence_score for r in results.values()) / total
    
    return {
        'total_message_versions': total,
        'with_consensus': consensus_count,
        'without_consensus': no_consensus_count,
        'by_confidence_level': by_confidence,
        'total_outliers': total_outliers,
        'average_confidence_score': round(avg_confidence, 3),
    }


def _group_by_confidence(
    results: dict[tuple[str, int], ConsensusResult]
) -> dict[str, list[str]]:
    """Group message names by confidence level."""
    grouped: dict[str, list[str]] = {
        'high': [],
        'medium': [],
        'low': [],
        'single_source': [],
        'no_consensus': [],
    }
    
    for (name, version), result in sorted(results.items()):
        key = f"{name}-v{version}"
        grouped[result.confidence].append(key)
    
    return grouped


def _serialize_results(
    results: dict[tuple[str, int], ConsensusResult]
) -> list[dict]:
    """Serialize all results to JSON-compatible format."""
    serialized = []
    
    for (name, version), result in sorted(results.items()):
        serialized.append({
            'message_name': name,
            'protocol_version': version,
            'has_consensus': result.has_consensus,
            'confidence': result.confidence,
            'confidence_score': round(result.confidence_score, 3),
            'fingerprint': result.winning_fingerprint,
            'agreement': f"{result.agreement_count}/{result.total_count}",
            'sources': result.sources,
            'outlier_count': len(result.outliers),
        })
    
    return serialized


def _collect_outliers(
    results: dict[tuple[str, int], ConsensusResult]
) -> list[dict]:
    """Collect all outliers for review."""
    outliers = []
    
    for (name, version), result in sorted(results.items()):
        for outlier in result.outliers:
            outliers.append({
                'message_name': name,
                'protocol_version': version,
                'source': outlier.source,
                'fingerprint': outlier.fingerprint,
                'winning_fingerprint': result.winning_fingerprint,
                'discrepancy': outlier.discrepancy_summary,
                'field_differences': outlier.field_differences,
            })
    
    return outliers


def generate_discrepancy_report(
    results: dict[tuple[str, int], ConsensusResult],
    output_path: Path | None = None,
) -> dict:
    """Generate focused report on discrepancies for manual review.
    
    Args:
        results: Voting results
        output_path: Optional path to write JSON report
    
    Returns:
        Report dict focused on discrepancies
    """
    # Filter to only results with outliers or no consensus
    problem_results = {
        k: v for k, v in results.items()
        if v.outliers or not v.has_consensus
    }
    
    report = {
        'generated_at': datetime.now().isoformat(),
        'summary': {
            'total_messages_with_issues': len(problem_results),
            'total_outliers': sum(len(r.outliers) for r in problem_results.values()),
            'no_consensus_count': sum(1 for r in problem_results.values() if not r.has_consensus),
        },
        'issues': [],
    }
    
    for (name, version), result in sorted(problem_results.items()):
        issue = {
            'message_name': name,
            'protocol_version': version,
            'has_consensus': result.has_consensus,
            'confidence': result.confidence,
            'agreement': f"{result.agreement_count}/{result.total_count}",
            'winning_fingerprint': result.winning_fingerprint,
            'agreeing_sources': result.sources,
            'outliers': [],
        }
        
        for outlier in result.outliers:
            issue['outliers'].append({
                'source': outlier.source,
                'fingerprint': outlier.fingerprint,
                'discrepancy': outlier.discrepancy_summary,
                'details': outlier.field_differences,
            })
        
        report['issues'].append(issue)
    
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
    
    return report


def print_summary(results: dict[tuple[str, int], ConsensusResult]) -> None:
    """Print human-readable summary to stdout."""
    summary = _generate_summary(results)
    
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    
    print(f"\nTotal message/version combinations: {summary['total_message_versions']}")
    print(f"With consensus: {summary['with_consensus']}")
    print(f"Without consensus: {summary['without_consensus']}")
    print(f"Average confidence score: {summary['average_confidence_score']:.1%}")
    
    print("\nBy confidence level:")
    for level in ['high', 'medium', 'low', 'single_source', 'no_consensus']:
        count = summary['by_confidence_level'].get(level, 0)
        if count > 0:
            print(f"  {level}: {count}")
    
    print(f"\nTotal outliers (extraction errors): {summary['total_outliers']}")
    
    # Show some problem messages
    no_consensus = [
        (k, v) for k, v in results.items() 
        if not v.has_consensus
    ]
    
    if no_consensus:
        print(f"\n--- Messages without consensus ({len(no_consensus)}) ---")
        for (name, version), result in no_consensus[:10]:
            print(f"  {name} v{version}: {result.agreement_count}/{result.total_count}")
        if len(no_consensus) > 10:
            print(f"  ... and {len(no_consensus) - 10} more")
    
    print()
