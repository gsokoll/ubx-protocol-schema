"""Structural fingerprinting for UBX message definitions.

Computes deterministic fingerprints from message field layouts to enable
comparison and voting across multiple extraction sources.

Fingerprint includes: normalized field name, byte offset, data type, size
Fingerprint excludes: description, unit, scale, bitfield details, reserved flag
"""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any


# UBX data type sizes in bytes
DATA_TYPE_SIZES = {
    'U1': 1, 'U2': 2, 'U4': 4, 'U8': 8,
    'I1': 1, 'I2': 2, 'I4': 4, 'I8': 8,
    'X1': 1, 'X2': 2, 'X4': 4, 'X8': 8,
    'R4': 4, 'R8': 8,
    'CH': 1,
}


@dataclass
class FieldFingerprint:
    """Normalized field data for fingerprinting."""
    name: str
    byte_offset: int
    data_type: str
    size: int
    
    def to_tuple(self) -> tuple:
        """Convert to hashable tuple."""
        return (self.name, self.byte_offset, self.data_type, self.size)


def normalize_field_name(name: str) -> str:
    """Normalize field name for comparison.
    
    - Lowercase
    - Remove underscores/hyphens for comparison
    - Normalize reserved field naming
    
    Examples:
        "iTOW" -> "itow"
        "reserved_0" -> "reserved"
        "reserved1" -> "reserved"
        "numSV" -> "numsv"
    """
    if not name:
        return ""
    
    # Lowercase
    normalized = name.lower()
    
    # Normalize reserved fields (reserved0, reserved_1, reserved1 -> reserved)
    if normalized.startswith("reserved"):
        # Strip trailing numbers and underscores
        normalized = re.sub(r'[_]?\d+$', '', normalized)
        return "reserved"
    
    return normalized


def normalize_data_type(data_type: Any) -> tuple[str, int]:
    """Normalize data type and compute size.
    
    Args:
        data_type: String type like "U4" or dict like {"array_of": "U1", "count": 4}
    
    Returns:
        (normalized_type_string, size_in_bytes)
    
    Examples:
        "U4" -> ("U4", 4)
        {"array_of": "U1", "count": 4} -> ("U1[4]", 4)
        {"array_of": "CH", "count": 30} -> ("CH[30]", 30)
    """
    if isinstance(data_type, str):
        size = DATA_TYPE_SIZES.get(data_type, 1)
        return (data_type, size)
    
    if isinstance(data_type, dict):
        if 'array_of' in data_type:
            base_type = data_type['array_of']
            # Handle case where base_type is also a dict (malformed extraction)
            if isinstance(base_type, dict):
                return (json.dumps(data_type, sort_keys=True), 1)
            count = data_type.get('count', 1)
            base_size = DATA_TYPE_SIZES.get(base_type, 1)
            # Handle variable counts (strings like "N", "variable", formulas)
            if isinstance(count, int):
                return (f"{base_type}[{count}]", base_size * count)
            else:
                # Variable length array - use count string but size 0
                return (f"{base_type}[{count}]", 0)
        
        # Handle other dict formats - convert to string for comparison
        return (json.dumps(data_type, sort_keys=True), 1)
    
    # Unknown type
    return (str(data_type), 1)


def compute_field_fingerprint(field: dict) -> FieldFingerprint:
    """Compute fingerprint for a single field.
    
    Args:
        field: Field dict from extraction with keys like:
            - name: str
            - byte_offset: int
            - data_type: str or dict
            - size_bytes: int (optional, computed if missing)
    
    Returns:
        FieldFingerprint with normalized values
    """
    name = normalize_field_name(field.get('name', ''))
    byte_offset_raw = field.get('byte_offset', 0)
    # Handle string offsets (formulas) by using -1 as placeholder
    byte_offset = byte_offset_raw if isinstance(byte_offset_raw, int) else -1
    
    data_type_raw = field.get('data_type', 'U1')
    data_type_str, computed_size = normalize_data_type(data_type_raw)
    
    # Use explicit size if provided, otherwise computed
    size = field.get('size_bytes', computed_size)
    
    return FieldFingerprint(
        name=name,
        byte_offset=byte_offset,
        data_type=data_type_str,
        size=size,
    )


def compute_message_fingerprint(message: dict) -> str:
    """Compute structural fingerprint for a message definition.
    
    Args:
        message: Message dict with 'fields' or 'payload.fields' key
    
    Returns:
        Hex string fingerprint (SHA-256 truncated to 16 chars)
    """
    # Extract fields from message (including from repeated_groups)
    fields = message.get('fields', [])
    payload = message.get('payload', {})
    if not fields and payload:
        fields = payload.get('fields', [])
    
    # Also include fields from repeated_groups (don't tag - treat same as top-level)
    repeated_groups = (payload.get('repeated_groups') or []) if payload else []
    rgroup_fields = []
    for rg in repeated_groups:
        for field in rg.get('fields', []):
            rgroup_fields.append(field)
    
    all_fields = list(fields) + rgroup_fields
    
    if not all_fields:
        return "empty_" + hashlib.sha256(b"no_fields").hexdigest()[:12]
    
    # Compute fingerprint for each field
    field_fingerprints = []
    for field in all_fields:
        fp = compute_field_fingerprint(field)
        field_fingerprints.append(fp.to_tuple())
    
    # Sort by byte offset for deterministic ordering
    field_fingerprints.sort(key=lambda x: (x[1], x[0]))  # (offset, name)
    
    # Hash the sorted field tuples
    fingerprint_data = json.dumps(field_fingerprints, sort_keys=True).encode('utf-8')
    full_hash = hashlib.sha256(fingerprint_data).hexdigest()
    
    return full_hash[:16]


def compute_message_fingerprint_detailed(message: dict) -> dict:
    """Compute fingerprint with detailed breakdown for debugging.
    
    Args:
        message: Message dict with 'fields' key
    
    Returns:
        Dict with fingerprint and per-field details
    """
    fields = message.get('fields', [])
    payload = message.get('payload', {})
    if not fields and payload:
        fields = payload.get('fields', [])
    
    # Also include fields from repeated_groups (don't tag - treat same as top-level)
    repeated_groups = (payload.get('repeated_groups') or []) if payload else []
    rgroup_fields = []
    for rg in repeated_groups:
        for field in rg.get('fields', []):
            rgroup_fields.append(field)
    
    all_fields = list(fields) + rgroup_fields
    
    field_details = []
    for field in all_fields:
        fp = compute_field_fingerprint(field)
        field_details.append({
            'original_name': field.get('name', ''),
            'normalized_name': fp.name,
            'byte_offset': fp.byte_offset,
            'original_data_type': field.get('data_type'),
            'normalized_data_type': fp.data_type,
            'size': fp.size,
            'tuple': fp.to_tuple(),
        })
    
    # Sort by byte offset
    field_details.sort(key=lambda x: (x['byte_offset'], x['normalized_name']))
    
    fingerprint = compute_message_fingerprint(message)
    
    return {
        'fingerprint': fingerprint,
        'field_count': len(field_details),
        'fields': field_details,
    }


def fingerprints_match(fp1: str, fp2: str) -> bool:
    """Check if two fingerprints match.
    
    Simple equality check, but abstracted for potential fuzzy matching later.
    """
    return fp1 == fp2


def compute_fingerprint_distance(fp_detailed1: dict, fp_detailed2: dict) -> dict:
    """Compute detailed difference between two fingerprints.
    
    Args:
        fp_detailed1, fp_detailed2: Results from compute_message_fingerprint_detailed
    
    Returns:
        Dict describing differences:
        - match: bool
        - field_count_diff: int
        - mismatched_fields: list of diffs
    """
    fields1 = {f['byte_offset']: f for f in fp_detailed1['fields']}
    fields2 = {f['byte_offset']: f for f in fp_detailed2['fields']}
    
    all_offsets = set(fields1.keys()) | set(fields2.keys())
    
    mismatches = []
    for offset in sorted(all_offsets):
        f1 = fields1.get(offset)
        f2 = fields2.get(offset)
        
        if f1 is None:
            mismatches.append({
                'offset': offset,
                'type': 'missing_in_first',
                'second': f2,
            })
        elif f2 is None:
            mismatches.append({
                'offset': offset,
                'type': 'missing_in_second',
                'first': f1,
            })
        elif f1['tuple'] != f2['tuple']:
            mismatches.append({
                'offset': offset,
                'type': 'field_differs',
                'first': f1,
                'second': f2,
            })
    
    return {
        'match': len(mismatches) == 0,
        'fingerprint1': fp_detailed1['fingerprint'],
        'fingerprint2': fp_detailed2['fingerprint'],
        'field_count_diff': fp_detailed1['field_count'] - fp_detailed2['field_count'],
        'mismatch_count': len(mismatches),
        'mismatches': mismatches,
    }
