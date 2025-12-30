"""Validation module for majority-voting based extraction validation.

This module implements a pipeline to validate LLM-extracted UBX message definitions
by comparing extractions across multiple sources and voting on correct interpretations.

See docs/majority-voting-pipeline.md for design documentation.
"""

from .fingerprint import (
    compute_field_fingerprint,
    compute_message_fingerprint,
    compute_message_fingerprint_detailed,
    compute_fingerprint_distance,
    normalize_field_name,
    normalize_data_type,
)

from .version_detect import (
    detect_version_field,
    get_protocol_version,
    VersionFieldInfo,
)

from .grouping import (
    group_extractions,
    get_group_summary,
    ExtractionSource,
    GroupedMessage,
    MessageGroup,
)

from .voting import (
    vote_on_group,
    vote_on_all_groups,
    filter_by_consensus,
    VotingConfig,
    ConsensusResult,
    Outlier,
)

from .report import (
    generate_validation_report,
    generate_discrepancy_report,
    print_summary,
)

from .output import (
    consensus_to_canonical,
    write_canonical_messages,
    update_canonical_with_new_source,
    generate_canonical_filename,
)

from .structural import (
    validate_message_structure,
    validate_extraction_file,
    get_failed_messages,
    build_reextraction_prompt,
    ValidationIssue,
    ValidationResult,
)

from .merge import (
    merge_bitfield_bits,
    merge_field_bitfields,
    merge_message_bitfields,
)

__all__ = [
    # Fingerprinting
    "compute_field_fingerprint",
    "compute_message_fingerprint",
    "compute_message_fingerprint_detailed",
    "compute_fingerprint_distance",
    "normalize_field_name",
    "normalize_data_type",
    # Version detection
    "detect_version_field",
    "get_protocol_version",
    "VersionFieldInfo",
    # Grouping
    "group_extractions",
    "get_group_summary",
    "ExtractionSource",
    "GroupedMessage",
    "MessageGroup",
    # Voting
    "vote_on_group",
    "vote_on_all_groups",
    "filter_by_consensus",
    "VotingConfig",
    "ConsensusResult",
    "Outlier",
    # Reporting
    "generate_validation_report",
    "generate_discrepancy_report",
    "print_summary",
    # Output
    "consensus_to_canonical",
    "write_canonical_messages",
    "update_canonical_with_new_source",
    "generate_canonical_filename",
    # Structural validation
    "validate_message_structure",
    "validate_extraction_file",
    "get_failed_messages",
    "build_reextraction_prompt",
    "ValidationIssue",
    "ValidationResult",
    # Bitfield merging
    "merge_bitfield_bits",
    "merge_field_bitfields",
    "merge_message_bitfields",
]
