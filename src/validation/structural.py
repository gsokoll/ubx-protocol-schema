"""Structural validation for UBX message extractions.

Validates that extracted message definitions are structurally sound:
- Sequential offsets (no unexpected gaps)
- No overlapping fields
- Field sizes match data types
- Total payload length consistency

When validation fails, can trigger re-extraction with error context.
"""

from dataclasses import dataclass, field
from typing import Any

from .fingerprint import DATA_TYPE_SIZES, normalize_data_type


@dataclass
class ValidationIssue:
    """A structural validation issue."""
    issue_type: str  # 'gap', 'overlap', 'size_mismatch', 'type_invalid'
    severity: str    # 'error', 'warning'
    field_name: str
    byte_offset: int
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of structural validation."""
    message_name: str
    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    
    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == 'error')
    
    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == 'warning')
    
    def to_prompt_context(self) -> str:
        """Generate context for re-extraction prompt."""
        if self.is_valid:
            return ""
        
        lines = [
            f"PREVIOUS EXTRACTION HAD {self.error_count} ERRORS:",
            "",
        ]
        
        for issue in self.issues:
            if issue.severity == 'error':
                lines.append(f"- {issue.message}")
        
        lines.append("")
        lines.append("Please carefully re-extract, paying attention to these issues.")
        
        return "\n".join(lines)


def get_field_size(data_type: Any) -> int:
    """Get size in bytes for a data type."""
    if isinstance(data_type, str):
        return DATA_TYPE_SIZES.get(data_type, 1)
    
    if isinstance(data_type, dict):
        if 'array_of' in data_type:
            base_type = data_type['array_of']
            count = data_type.get('count', 1)
            base_size = DATA_TYPE_SIZES.get(base_type, 1)
            return base_size * count
    
    return 1


def validate_message_structure(message: dict) -> ValidationResult:
    """Validate structural integrity of a message extraction.
    
    Checks:
    1. Fields are sorted by offset
    2. No gaps between fields (warning, may be intentional padding)
    3. No overlapping fields (error)
    4. Field sizes match declared data types
    5. Payload length consistency (if declared)
    
    Args:
        message: Message dict with 'fields' key
    
    Returns:
        ValidationResult with any issues found
    """
    msg_name = message.get('name', 'unknown')
    issues: list[ValidationIssue] = []
    
    # Get fields
    fields = message.get('fields', [])
    if not fields and message.get('payload'):
        fields = message['payload'].get('fields', [])
    
    if not fields:
        return ValidationResult(
            message_name=msg_name,
            is_valid=True,
            issues=[ValidationIssue(
                issue_type='empty',
                severity='warning',
                field_name='',
                byte_offset=0,
                message='Message has no fields',
            )],
        )
    
    # Sort fields by offset
    sorted_fields = sorted(fields, key=lambda f: f.get('byte_offset', 0))
    
    # Check each field
    expected_offset = 0
    
    for i, field_data in enumerate(sorted_fields):
        field_name = field_data.get('name', f'field_{i}')
        byte_offset = field_data.get('byte_offset', 0)
        data_type = field_data.get('data_type', 'U1')
        declared_size = field_data.get('size_bytes')
        computed_size = get_field_size(data_type)
        
        # Check for gap
        if byte_offset > expected_offset:
            gap_size = byte_offset - expected_offset
            issues.append(ValidationIssue(
                issue_type='gap',
                severity='warning',
                field_name=field_name,
                byte_offset=byte_offset,
                message=f"Gap of {gap_size} bytes before field '{field_name}' at offset {byte_offset} (expected {expected_offset})",
                details={'gap_size': gap_size, 'expected_offset': expected_offset},
            ))
        
        # Check for overlap
        if byte_offset < expected_offset:
            overlap_size = expected_offset - byte_offset
            issues.append(ValidationIssue(
                issue_type='overlap',
                severity='error',
                field_name=field_name,
                byte_offset=byte_offset,
                message=f"Field '{field_name}' at offset {byte_offset} overlaps with previous field (expected offset >= {expected_offset})",
                details={'overlap_size': overlap_size, 'expected_offset': expected_offset},
            ))
        
        # Check size consistency
        if declared_size is not None and declared_size != computed_size:
            issues.append(ValidationIssue(
                issue_type='size_mismatch',
                severity='warning',
                field_name=field_name,
                byte_offset=byte_offset,
                message=f"Field '{field_name}' declared size ({declared_size}) differs from computed size ({computed_size}) for type {data_type}",
                details={'declared_size': declared_size, 'computed_size': computed_size},
            ))
        
        # Check for invalid type
        if isinstance(data_type, str) and data_type not in DATA_TYPE_SIZES:
            issues.append(ValidationIssue(
                issue_type='type_invalid',
                severity='warning',
                field_name=field_name,
                byte_offset=byte_offset,
                message=f"Field '{field_name}' has unrecognized type '{data_type}'",
                details={'data_type': data_type},
            ))
        
        # Update expected offset for next field
        expected_offset = byte_offset + computed_size
    
    # Check payload length consistency
    payload_length = message.get('payload_length')
    if payload_length:
        if isinstance(payload_length, dict) and 'fixed' in payload_length:
            declared_length = payload_length['fixed']
            if expected_offset != declared_length:
                issues.append(ValidationIssue(
                    issue_type='length_mismatch',
                    severity='warning',
                    field_name='',
                    byte_offset=expected_offset,
                    message=f"Computed payload length ({expected_offset}) differs from declared ({declared_length})",
                    details={'computed': expected_offset, 'declared': declared_length},
                ))
    
    # Determine if valid (no errors, warnings are OK)
    is_valid = all(i.severity != 'error' for i in issues)
    
    return ValidationResult(
        message_name=msg_name,
        is_valid=is_valid,
        issues=issues,
    )


def validate_extraction_file(messages: list[dict]) -> dict[str, ValidationResult]:
    """Validate all messages in an extraction file.
    
    Args:
        messages: List of message dicts
    
    Returns:
        Dict mapping message name to ValidationResult
    """
    results = {}
    for msg in messages:
        name = msg.get('name', 'unknown')
        results[name] = validate_message_structure(msg)
    return results


def get_failed_messages(
    validation_results: dict[str, ValidationResult]
) -> list[tuple[str, ValidationResult]]:
    """Get messages that failed validation.
    
    Args:
        validation_results: Results from validate_extraction_file
    
    Returns:
        List of (message_name, result) tuples for failed messages
    """
    return [
        (name, result)
        for name, result in validation_results.items()
        if not result.is_valid
    ]


def build_reextraction_prompt(
    message_name: str,
    previous_extraction: dict,
    validation_result: ValidationResult,
) -> str:
    """Build a prompt for re-extracting a message with error context.
    
    Args:
        message_name: Name of the message to re-extract
        previous_extraction: The previous failed extraction
        validation_result: Validation result with issues
    
    Returns:
        Prompt string with context for re-extraction
    """
    lines = [
        f"Re-extract message {message_name} from the PDF pages.",
        "",
        "IMPORTANT: The previous extraction had structural errors that must be fixed:",
        "",
    ]
    
    for issue in validation_result.issues:
        if issue.severity == 'error':
            lines.append(f"ERROR: {issue.message}")
        else:
            lines.append(f"WARNING: {issue.message}")
    
    lines.append("")
    lines.append("Previous extraction for reference (contains errors):")
    lines.append("```json")
    
    # Include simplified previous extraction
    prev_fields = previous_extraction.get('fields', [])
    if not prev_fields and previous_extraction.get('payload'):
        prev_fields = previous_extraction['payload'].get('fields', [])
    
    for f in prev_fields[:10]:  # Limit to first 10 fields
        lines.append(f"  offset {f.get('byte_offset', '?')}: {f.get('name', '?')} ({f.get('data_type', '?')})")
    
    if len(prev_fields) > 10:
        lines.append(f"  ... and {len(prev_fields) - 10} more fields")
    
    lines.append("```")
    lines.append("")
    lines.append("Please carefully re-extract all fields with correct byte offsets.")
    lines.append("Ensure offsets are sequential with no overlaps.")
    lines.append("Verify field sizes match the offset differences.")
    
    return "\n".join(lines)
