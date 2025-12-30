"""Voting and adjudication for UBX message validation.

Implements majority-rules voting to determine canonical message definitions
from multiple extraction sources.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .grouping import MessageGroup, GroupedMessage
from .fingerprint import compute_fingerprint_distance
from .merge import merge_message_bitfields


@dataclass
class VotingConfig:
    """Configuration for voting behavior."""
    threshold: float = 0.75  # Minimum agreement for consensus
    min_sources: int = 3     # Minimum sources for high confidence
    
    def __post_init__(self):
        if not 0 < self.threshold <= 1:
            raise ValueError("threshold must be between 0 and 1")
        if self.min_sources < 1:
            raise ValueError("min_sources must be at least 1")


@dataclass
class Outlier:
    """An extraction that disagrees with consensus."""
    source: str
    fingerprint: str
    discrepancy_summary: str
    field_differences: list[dict]


@dataclass 
class ConsensusResult:
    """Result of voting on a message group."""
    message_name: str
    protocol_version: int
    
    # Consensus status
    has_consensus: bool
    confidence: str  # "high", "medium", "low", "single_source", "no_consensus"
    confidence_score: float  # 0.0 to 1.0
    
    # Winning fingerprint
    winning_fingerprint: str | None
    winning_message: dict | None  # Full message data from winning source
    
    # Voting details
    sources: list[str]
    agreement_count: int
    total_count: int
    
    # Outliers (sources that disagreed)
    outliers: list[Outlier] = field(default_factory=list)
    
    # Metadata
    last_validated: str = field(default_factory=lambda: datetime.now().isoformat()[:10])


def vote_on_group(group: MessageGroup, config: VotingConfig | None = None) -> ConsensusResult:
    """Vote on a message group to determine consensus.
    
    Args:
        group: MessageGroup containing all extractions for (message_name, protocol_version)
        config: Voting configuration (uses defaults if not provided)
    
    Returns:
        ConsensusResult with voting outcome
    """
    if config is None:
        config = VotingConfig()
    
    # Handle empty group
    if not group.messages:
        return ConsensusResult(
            message_name=group.message_name,
            protocol_version=group.protocol_version,
            has_consensus=False,
            confidence="no_consensus",
            confidence_score=0.0,
            winning_fingerprint=None,
            winning_message=None,
            sources=[],
            agreement_count=0,
            total_count=0,
        )
    
    # Handle single source
    if group.source_count == 1:
        msg = group.messages[0]
        return ConsensusResult(
            message_name=group.message_name,
            protocol_version=group.protocol_version,
            has_consensus=True,
            confidence="single_source",
            confidence_score=0.5,  # Single source = 50% confidence
            winning_fingerprint=msg.fingerprint,
            winning_message=msg.message_data,
            sources=[msg.source.short_name],
            agreement_count=1,
            total_count=1,
        )
    
    # Count fingerprints
    fingerprint_counts = group.fingerprint_counts
    total = group.source_count
    
    # Find winner (most common fingerprint)
    winning_fingerprint = max(fingerprint_counts.keys(), key=lambda fp: fingerprint_counts[fp])
    agreement_count = fingerprint_counts[winning_fingerprint]
    agreement_ratio = agreement_count / total
    
    # Determine consensus
    has_consensus = agreement_ratio >= config.threshold
    
    # Determine confidence level
    if agreement_ratio >= 0.9 and total >= config.min_sources:
        confidence = "high"
        confidence_score = agreement_ratio
    elif agreement_ratio >= config.threshold and total >= config.min_sources:
        confidence = "medium"
        confidence_score = agreement_ratio * 0.9
    elif agreement_ratio >= config.threshold:
        confidence = "low"
        confidence_score = agreement_ratio * 0.7
    else:
        confidence = "no_consensus"
        confidence_score = agreement_ratio * 0.5
    
    # Get winning message (first one with winning fingerprint)
    winning_message = None
    winning_detailed = None
    agreeing_messages = []  # Collect all messages with winning fingerprint for merging
    
    for msg in group.messages:
        if msg.fingerprint == winning_fingerprint:
            if winning_message is None:
                winning_message = msg.message_data
                winning_detailed = msg.fingerprint_detailed
            agreeing_messages.append(msg.message_data)
    
    # Merge bitfield bits from all agreeing sources to get superset
    if winning_message and len(agreeing_messages) > 1:
        winning_message = merge_message_bitfields(winning_message, agreeing_messages)
    
    # Collect sources
    agreeing_sources = []
    outliers = []
    
    for msg in group.messages:
        if msg.fingerprint == winning_fingerprint:
            agreeing_sources.append(msg.source.short_name)
        else:
            # This is an outlier - compute difference
            diff = compute_fingerprint_distance(
                winning_detailed,
                msg.fingerprint_detailed,
            )
            
            # Summarize differences
            diff_summary = _summarize_differences(diff)
            
            outliers.append(Outlier(
                source=msg.source.short_name,
                fingerprint=msg.fingerprint,
                discrepancy_summary=diff_summary,
                field_differences=diff['mismatches'],
            ))
    
    return ConsensusResult(
        message_name=group.message_name,
        protocol_version=group.protocol_version,
        has_consensus=has_consensus,
        confidence=confidence,
        confidence_score=confidence_score,
        winning_fingerprint=winning_fingerprint,
        winning_message=winning_message,
        sources=agreeing_sources,
        agreement_count=agreement_count,
        total_count=total,
        outliers=outliers,
    )


def _summarize_differences(diff: dict) -> str:
    """Create human-readable summary of differences."""
    if diff['match']:
        return "No differences"
    
    parts = []
    
    if diff['field_count_diff'] != 0:
        parts.append(f"field count differs by {diff['field_count_diff']}")
    
    for mismatch in diff['mismatches'][:3]:  # Limit to first 3
        mtype = mismatch['type']
        offset = mismatch['offset']
        
        if mtype == 'missing_in_first':
            parts.append(f"missing field at offset {offset}")
        elif mtype == 'missing_in_second':
            parts.append(f"extra field at offset {offset}")
        elif mtype == 'field_differs':
            f1 = mismatch['first']
            f2 = mismatch['second']
            parts.append(f"field at offset {offset}: {f1['normalized_name']}({f1['normalized_data_type']}) vs {f2['normalized_name']}({f2['normalized_data_type']})")
    
    if len(diff['mismatches']) > 3:
        parts.append(f"...and {len(diff['mismatches']) - 3} more differences")
    
    return "; ".join(parts) if parts else "Unknown differences"


def vote_on_all_groups(
    groups: dict[tuple[str, int], MessageGroup],
    config: VotingConfig | None = None,
) -> dict[tuple[str, int], ConsensusResult]:
    """Vote on all message groups.
    
    Args:
        groups: Dict mapping (message_name, protocol_version) to MessageGroup
        config: Voting configuration
    
    Returns:
        Dict mapping same keys to ConsensusResult
    """
    results = {}
    for key, group in groups.items():
        results[key] = vote_on_group(group, config)
    return results


def filter_by_consensus(
    results: dict[tuple[str, int], ConsensusResult],
    require_consensus: bool = True,
    min_confidence: str | None = None,
) -> dict[tuple[str, int], ConsensusResult]:
    """Filter voting results by consensus criteria.
    
    Args:
        results: Voting results from vote_on_all_groups
        require_consensus: Only include results with consensus
        min_confidence: Minimum confidence level ("high", "medium", "low")
    
    Returns:
        Filtered results dict
    """
    confidence_levels = ["no_consensus", "single_source", "low", "medium", "high"]
    min_level_idx = 0
    if min_confidence:
        min_level_idx = confidence_levels.index(min_confidence)
    
    filtered = {}
    for key, result in results.items():
        if require_consensus and not result.has_consensus:
            continue
        
        result_level_idx = confidence_levels.index(result.confidence)
        if result_level_idx < min_level_idx:
            continue
        
        filtered[key] = result
    
    return filtered
