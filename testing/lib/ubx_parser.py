"""Parse UBX binary messages using schema definitions."""

import struct
from typing import Any, Optional

from .schema_loader import get_message_by_ids, parse_hex_id, select_variant_by_payload

# UBX sync characters
SYNC_CHAR_1 = 0xB5
SYNC_CHAR_2 = 0x62

# Data type to struct format and size
DATA_TYPE_MAP = {
    "U1": ("B", 1),
    "I1": ("b", 1),
    "X1": ("B", 1),
    "U2": ("H", 2),
    "I2": ("h", 2),
    "X2": ("H", 2),
    "U4": ("I", 4),
    "I4": ("i", 4),
    "X4": ("I", 4),
    "R4": ("f", 4),
    "R8": ("d", 8),
    "CH": ("c", 1),
}


class UBXParseError(Exception):
    """Exception raised when parsing fails."""
    pass


def verify_checksum(data: bytes) -> bool:
    """Verify UBX checksum. Data should be class+id+length+payload."""
    if len(data) < 2:
        return False
    
    ck_a = 0
    ck_b = 0
    for byte in data[:-2]:  # Exclude checksum bytes
        ck_a = (ck_a + byte) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    
    return ck_a == data[-2] and ck_b == data[-1]


def decode_field(data: bytes, offset: int, data_type) -> tuple[Any, int]:
    """Decode a single field from bytes.

    Returns:
        Tuple of (value, bytes_consumed)
    """
    # Handle data_type being a dict
    if isinstance(data_type, dict):
        if "array_of" in data_type:
            base_type = data_type["array_of"]
            # Handle nested structures - can't decode them
            if isinstance(base_type, dict):
                return [], 0
            count = data_type.get("count", 1)
            # Handle variable count
            if not isinstance(count, int):
                return [], 0
            if base_type == "CH":
                end = offset + count
                if end > len(data):
                    end = len(data)
                raw = data[offset:end]
                value = raw.decode("ascii", errors="replace").rstrip("\x00")
                return value, count
            else:
                fmt, size = DATA_TYPE_MAP.get(base_type, ("B", 1))
                values = []
                for i in range(count):
                    pos = offset + i * size
                    if pos + size <= len(data):
                        values.append(struct.unpack_from(f"<{fmt}", data, pos)[0])
                    else:
                        values.append(0)
                return values, size * count
        # Handle complex element structures
        if "elements" in data_type or "num_elements_field" in data_type:
            return [], 0
        data_type = data_type.get("type", "U1")
    if not isinstance(data_type, str):
        data_type = "U1"

    # Handle array types
    if "[" in data_type:
        base_type = data_type.split("[")[0]
        count_str = data_type.split("[")[1].rstrip("]")
        # Handle variable-length arrays like "U1[]"
        if not count_str:
            return [], 0
        try:
            count = int(count_str)
        except ValueError:
            return [], 0
        
        if base_type == "CH":
            # String/character array
            end = offset + count
            if end > len(data):
                end = len(data)
            raw = data[offset:end]
            # Decode and strip null bytes
            value = raw.decode("ascii", errors="replace").rstrip("\x00")
            return value, count
        else:
            # Numeric array
            fmt, size = DATA_TYPE_MAP.get(base_type, ("B", 1))
            values = []
            for i in range(count):
                pos = offset + i * size
                if pos + size <= len(data):
                    values.append(struct.unpack_from(f"<{fmt}", data, pos)[0])
                else:
                    values.append(0)
            return values, size * count
    
    # Single value
    fmt, size = DATA_TYPE_MAP.get(data_type, ("B", 1))
    if offset + size > len(data):
        return 0, size
    
    value = struct.unpack_from(f"<{fmt}", data, offset)[0]
    return value, size


def parse_ubx_message(data: bytes, message_def: Optional[dict] = None) -> dict:
    """Parse a UBX binary message using schema definition.
    
    Args:
        data: Raw UBX message bytes (including sync chars and checksum)
        message_def: Optional message definition. If None, will look up by class/id.
    
    Returns:
        Dict with parsed message info and field values
    
    Raises:
        UBXParseError: If parsing fails
    """
    # Validate minimum length
    if len(data) < 8:  # sync(2) + class(1) + id(1) + len(2) + checksum(2)
        raise UBXParseError(f"Message too short: {len(data)} bytes")
    
    # Check sync characters
    if data[0] != SYNC_CHAR_1 or data[1] != SYNC_CHAR_2:
        raise UBXParseError(f"Invalid sync characters: {data[0]:02X} {data[1]:02X}")
    
    # Extract header
    class_id = data[2]
    msg_id = data[3]
    payload_len = struct.unpack_from("<H", data, 4)[0]
    
    # Validate length
    expected_len = 6 + payload_len + 2  # header + payload + checksum
    if len(data) < expected_len:
        raise UBXParseError(f"Message truncated: expected {expected_len}, got {len(data)}")
    
    # Verify checksum
    checksum_data = data[2:6 + payload_len + 2]  # class through checksum
    if not verify_checksum(checksum_data):
        raise UBXParseError("Checksum verification failed")
    
    # Extract payload
    payload = data[6:6 + payload_len]
    
    # Look up message definition if not provided
    if message_def is None:
        message_def = get_message_by_ids(class_id, msg_id)

    if message_def is None:
        # Return basic info without field parsing
        return {
            "class_id": class_id,
            "message_id": msg_id,
            "name": f"UBX-{class_id:02X}-{msg_id:02X}",
            "payload_length": payload_len,
            "payload_raw": payload.hex(),
            "fields": {},
            "parsed": False,
        }

    # Handle multi-variant messages
    variant = None
    variant_name = None
    payload_source = message_def.get("payload", {})

    if "variants" in message_def:
        variant = select_variant_by_payload(message_def, payload)
        if variant:
            variant_name = variant.get("name")
            payload_source = variant.get("payload", {})
        else:
            # Couldn't determine variant, return basic info
            return {
                "class_id": class_id,
                "message_id": msg_id,
                "name": message_def.get("name", f"UBX-{class_id:02X}-{msg_id:02X}"),
                "payload_length": payload_len,
                "payload_raw": payload.hex(),
                "fields": {},
                "parsed": False,
                "variant_error": "Could not determine variant from payload",
            }

    # Parse fields according to schema
    fields_def = payload_source.get("fields", [])
    # Handle fields with None or non-integer byte_offsets by putting them at the end
    def get_sort_key(f):
        offset = f.get("byte_offset")
        if isinstance(offset, int):
            return (0, offset)  # Integer offsets first, sorted by value
        return (1, 0)  # Non-integer offsets (None, strings) at the end
    sorted_fields = sorted(fields_def, key=get_sort_key)
    
    parsed_fields = {}
    for field_def in sorted_fields:
        name = field_def.get("name")
        data_type = field_def.get("data_type", "U1")
        byte_offset = field_def.get("byte_offset")

        # Skip fields with non-integer byte_offsets (variable position fields)
        if not isinstance(byte_offset, int):
            continue

        if byte_offset >= len(payload):
            # Field beyond payload (variable length message)
            continue

        value, _ = decode_field(payload, byte_offset, data_type)
        parsed_fields[name] = value

    result = {
        "class_id": class_id,
        "message_id": msg_id,
        "name": message_def.get("name", f"UBX-{class_id:02X}-{msg_id:02X}"),
        "payload_length": payload_len,
        "fields": parsed_fields,
        "parsed": True,
    }

    # Add variant info if this is a multi-variant message
    if variant_name:
        result["variant"] = variant_name
        # Also provide legacy alias name for compatibility
        result["variant_alias"] = f"{message_def.get('name')}-{variant_name}"

    return result


def extract_ubx_messages(data: bytes) -> list[bytes]:
    """Extract individual UBX messages from a byte stream.
    
    Args:
        data: Raw byte stream potentially containing multiple messages
    
    Returns:
        List of individual UBX message bytes
    """
    messages = []
    i = 0
    
    while i < len(data) - 7:
        # Look for sync characters
        if data[i] == SYNC_CHAR_1 and data[i + 1] == SYNC_CHAR_2:
            # Extract length
            if i + 6 <= len(data):
                payload_len = struct.unpack_from("<H", data, i + 4)[0]
                msg_len = 6 + payload_len + 2
                
                if i + msg_len <= len(data):
                    messages.append(data[i:i + msg_len])
                    i += msg_len
                    continue
        i += 1
    
    return messages
