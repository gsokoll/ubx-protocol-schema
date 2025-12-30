"""Version field detection for UBX messages.

Heuristically identifies the protocol version field in message payloads.
Most UBX messages have a version field at offset 0 or 1 with type U1.

If no version field is detected, returns version 0 (implicit).
"""

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class VersionFieldInfo:
    """Information about a detected version field."""
    detected: bool
    field_name: str | None
    byte_offset: int | None
    value: int | None  # The version value if extractable from description
    confidence: str  # "high", "medium", "low", "none"
    reason: str


# Common version field names (case-insensitive patterns)
VERSION_FIELD_PATTERNS = [
    r'^version$',
    r'^msgver$',
    r'^msg_version$',
    r'^protocolversion$',
    r'^ver$',
]

# Fields that look like version but aren't
FALSE_POSITIVE_PATTERNS = [
    r'^swversion',
    r'^hwversion',
    r'^romversion',
    r'^fwversion',
    r'^firmware',
]


def detect_version_field(message: dict) -> VersionFieldInfo:
    """Detect the protocol version field in a message.
    
    Heuristics (in priority order):
    1. Field named "version" at offset 0 or 1 with type U1 -> high confidence
    2. Field named "version" elsewhere -> medium confidence
    3. Field at offset 0 with type U1 and description mentions "version" -> medium
    4. No version field found -> implicit version 0
    
    Args:
        message: Message dict with 'fields' key
    
    Returns:
        VersionFieldInfo with detection result
    """
    fields = message.get('fields', [])
    if not fields and message.get('payload'):
        fields = message['payload'].get('fields', [])
    
    if not fields:
        return VersionFieldInfo(
            detected=False,
            field_name=None,
            byte_offset=None,
            value=0,
            confidence="none",
            reason="No fields in message",
        )
    
    # Build field lookup by offset
    fields_by_offset = {}
    for f in fields:
        offset = f.get('byte_offset', -1)
        if offset >= 0:
            fields_by_offset[offset] = f
    
    # Strategy 1: Look for field named "version" at offset 0 or 1
    for offset in [0, 1]:
        if offset in fields_by_offset:
            field = fields_by_offset[offset]
            name = field.get('name', '').lower()
            data_type = _normalize_type(field.get('data_type'))
            
            if _matches_version_pattern(name) and data_type == 'U1':
                version_value = _extract_version_value(field)
                return VersionFieldInfo(
                    detected=True,
                    field_name=field.get('name'),
                    byte_offset=offset,
                    value=version_value,
                    confidence="high",
                    reason=f"Field '{field.get('name')}' at offset {offset} with type U1",
                )
    
    # Strategy 2: Look for field named "version" anywhere
    for field in fields:
        name = field.get('name', '').lower()
        if _matches_version_pattern(name):
            data_type = _normalize_type(field.get('data_type'))
            offset = field.get('byte_offset', -1)
            
            # Skip if it's a false positive (e.g., swVersion)
            if _is_false_positive(name):
                continue
            
            version_value = _extract_version_value(field)
            confidence = "medium" if data_type == 'U1' else "low"
            
            return VersionFieldInfo(
                detected=True,
                field_name=field.get('name'),
                byte_offset=offset,
                value=version_value,
                confidence=confidence,
                reason=f"Field '{field.get('name')}' at offset {offset}",
            )
    
    # Strategy 3: Check offset 0 description for version hints
    if 0 in fields_by_offset:
        field = fields_by_offset[0]
        desc = (field.get('description') or '').lower()
        if 'version' in desc and 'message' in desc:
            version_value = _extract_version_value(field)
            return VersionFieldInfo(
                detected=True,
                field_name=field.get('name'),
                byte_offset=0,
                value=version_value,
                confidence="medium",
                reason=f"Field at offset 0 description mentions version",
            )
    
    # No version field detected -> implicit version 0
    return VersionFieldInfo(
        detected=False,
        field_name=None,
        byte_offset=None,
        value=0,
        confidence="none",
        reason="No version field detected, using implicit version 0",
    )


def _matches_version_pattern(name: str) -> bool:
    """Check if field name matches version field patterns."""
    name_lower = name.lower()
    for pattern in VERSION_FIELD_PATTERNS:
        if re.match(pattern, name_lower):
            return True
    return False


def _is_false_positive(name: str) -> bool:
    """Check if field name is a false positive (not protocol version)."""
    name_lower = name.lower()
    for pattern in FALSE_POSITIVE_PATTERNS:
        if re.match(pattern, name_lower):
            return True
    return False


def _normalize_type(data_type: Any) -> str:
    """Normalize data type to string."""
    if isinstance(data_type, str):
        return data_type
    if isinstance(data_type, dict):
        return data_type.get('array_of', 'unknown')
    return str(data_type)


def _extract_version_value(field: dict) -> int | None:
    """Try to extract version value from field description.
    
    Looks for patterns like:
    - "Message version (0x00)"
    - "version = 0"
    - "Version 1"
    """
    desc = field.get('description', '') or ''
    
    # Pattern: (0x00) or (0x01) or (0x02 for this version)
    match = re.search(r'\(0x([0-9a-fA-F]+)[\s\)]', desc)
    if match:
        return int(match.group(1), 16)
    
    # Pattern: 0x00, 0x01, 0x02 anywhere
    match = re.search(r'0x([0-9a-fA-F]+)', desc)
    if match:
        return int(match.group(1), 16)
    
    # Pattern: "version = N" or "version=N"
    match = re.search(r'version\s*[=:]\s*(\d+)', desc, re.IGNORECASE)
    if match:
        return int(match.group(1))
    
    # Pattern: "Version N" at end or standalone
    match = re.search(r'version\s+(\d+)\b', desc, re.IGNORECASE)
    if match:
        return int(match.group(1))
    
    return None


def get_protocol_version(message: dict) -> int:
    """Get the protocol version for a message.
    
    Convenience function that returns just the version number.
    
    Version logic:
    - If no version field detected: return 0 (implicit V0 format)
    - If version field detected with value: return that value
    - If version field detected but no value extracted: return 1 (V1 format)
    
    This handles messages like RXM-PMREQ where:
    - V0 format (old): No version field, starts with duration@0
    - V1 format (new): Has version field at offset 0 (value=0x00)
    
    The presence of a version field itself indicates a newer format.
    
    Args:
        message: Message dict with 'fields' key
    
    Returns:
        Protocol version as integer
    """
    info = detect_version_field(message)
    
    if not info.detected:
        # No version field = implicit V0 (old format)
        return 0
    
    if info.value is not None:
        return info.value
    
    # Version field exists but value not extracted = V1 format (new format)
    # This handles cases where description doesn't contain parseable version
    return 1
