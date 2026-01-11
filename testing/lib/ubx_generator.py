"""Generate UBX binary messages from schema definitions."""

import struct
import random
from typing import Any, Optional

from .schema_loader import parse_hex_id, get_variant_by_alias

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
    "CH": ("c", 1),  # Character
}


def calculate_checksum(data: bytes) -> tuple[int, int]:
    """Calculate UBX checksum (Fletcher algorithm)."""
    ck_a = 0
    ck_b = 0
    for byte in data:
        ck_a = (ck_a + byte) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return ck_a, ck_b


def get_field_size(data_type) -> int:
    """Get the size in bytes for a data type."""
    # Handle data_type being a dict with array_of
    if isinstance(data_type, dict):
        if "array_of" in data_type:
            base_type = data_type["array_of"]
            # Handle nested structures (complex array_of with dict)
            if isinstance(base_type, dict):
                return 0  # Can't determine size of complex nested structures
            count = data_type.get("count", 1)
            # Handle variable count (string like 'N' or count_field) - use 0 for variable-length
            if not isinstance(count, int):
                return 0
            base_size = DATA_TYPE_MAP.get(base_type, ("B", 1))[1]
            return base_size * count
        # Handle other dict formats (num_elements_field, elements, etc.)
        if "elements" in data_type or "num_elements_field" in data_type:
            return 0  # Variable-length complex structure
        data_type = data_type.get("type", "U1")
    if not isinstance(data_type, str):
        return 1

    # Handle array types like "U1[6]" or "CH[30]" or "U1[]" (variable length)
    if "[" in data_type:
        base_type = data_type.split("[")[0]
        count_str = data_type.split("[")[1].rstrip("]")
        if not count_str:  # Empty count like "U1[]"
            return 0
        try:
            count = int(count_str)
        except ValueError:
            return 0  # Variable count like "U1[N]"
        base_size = DATA_TYPE_MAP.get(base_type, ("B", 1))[1]
        return base_size * count

    return DATA_TYPE_MAP.get(data_type, ("B", 1))[1]


def get_message_payload(message: dict, variant_name: Optional[str] = None) -> tuple[dict, Optional[dict]]:
    """Get payload definition from a message, handling variants.

    Args:
        message: Message definition from schema
        variant_name: Optional variant name for multi-variant messages

    Returns:
        Tuple of (payload_dict, variant_dict or None)
    """
    if "variants" in message and message["variants"]:
        variants = message["variants"]
        if variant_name:
            for v in variants:
                if v.get("name") == variant_name:
                    return v.get("payload", {}), v
            # Variant not found, use first one
            return variants[0].get("payload", {}), variants[0]
        else:
            # No variant specified, use first one
            return variants[0].get("payload", {}), variants[0]
    else:
        return message.get("payload", {}), None


def generate_test_values(message: dict, num_repeated: int = 1, variant_name: Optional[str] = None) -> dict:
    """Generate random but valid test values for a message's fields.

    Args:
        message: Message definition from schema
        num_repeated: Number of repeated group instances to generate
        variant_name: Optional variant name for multi-variant messages

    Returns:
        Dict with field values and optional _repeated_groups data
    """
    values = {}
    payload, variant = get_message_payload(message, variant_name)

    # If this is a variant, include the discriminator value
    if variant and "discriminator" in variant:
        disc = variant["discriminator"]
        if "field" in disc and "value" in disc:
            values[disc["field"]] = disc["value"]
    fields = payload.get("fields", [])
    repeated_groups = payload.get("repeated_groups", [])
    
    # Find count fields that control repeated groups
    count_fields = set()
    for rg in repeated_groups:
        if rg.get("count_field"):
            count_fields.add(rg["count_field"])
    
    for field in fields:
        name = field.get("name")
        data_type = field.get("data_type", "U1")
        
        if field.get("reserved"):
            # Reserved fields get zeros
            values[name] = _generate_zero_value(data_type)
            continue
        
        # Use fixed_value if specified (e.g., MGA type discriminators)
        if "fixed_value" in field:
            fv = field["fixed_value"]
            # Parse hex strings to integers
            if isinstance(fv, str) and fv.startswith("0x"):
                fv = int(fv, 16)
            values[name] = fv
            continue
        
        # Set count fields to num_repeated
        if name in count_fields:
            values[name] = num_repeated
            continue
        
        values[name] = _generate_value_for_type(data_type)
    
    # Generate repeated group values
    if repeated_groups:
        values["_repeated_groups"] = {}
        for rg in repeated_groups:
            rg_name = rg.get("name", "group")
            rg_fields = rg.get("fields", [])
            instances = []
            for _ in range(num_repeated):
                instance = {}
                for field in rg_fields:
                    fname = field.get("name")
                    ftype = field.get("data_type", "U1")
                    if field.get("reserved"):
                        instance[fname] = _generate_zero_value(ftype)
                    else:
                        instance[fname] = _generate_value_for_type(ftype)
                instances.append(instance)
            values["_repeated_groups"][rg_name] = instances
    
    return values


def _generate_zero_value(data_type) -> Any:
    """Generate a zero/empty value for a data type."""
    if isinstance(data_type, dict):
        if "array_of" in data_type:
            count = data_type.get("count", 1)
            # Handle variable count (string like 'N') - use empty array
            if not isinstance(count, int):
                return []
            return [0] * count
        data_type = data_type.get("type", "U1")
    if not isinstance(data_type, str):
        return 0
    if "[" in data_type:
        base_type = data_type.split("[")[0]
        count = int(data_type.split("[")[1].rstrip("]"))
        if base_type == "CH":
            return "\x00" * count
        return [0] * count
    return 0


def _generate_value_for_type(data_type) -> Any:
    """Generate a random value for a data type (handles dict and string types)."""
    if isinstance(data_type, dict):
        if "array_of" in data_type:
            base_type = data_type["array_of"]
            # Handle nested structures - skip them
            if isinstance(base_type, dict):
                return []
            count = data_type.get("count", 1)
            # Handle variable count (string like 'N' or count_field) - use empty array
            if not isinstance(count, int):
                return []
            if base_type == "CH":
                return "A" * count
            return [_random_value_for_type(base_type) for _ in range(count)]
        # Handle complex element structures
        if "elements" in data_type or "num_elements_field" in data_type:
            return []
        data_type = data_type.get("type", "U1")
    if not isinstance(data_type, str):
        return 0
    if "[" in data_type:
        base_type = data_type.split("[")[0]
        count_str = data_type.split("[")[1].rstrip("]")
        if not count_str:  # Variable length like "U1[]"
            return []
        try:
            count = int(count_str)
        except ValueError:
            return []
        if base_type == "CH":
            return "A" * count
        return [_random_value_for_type(base_type) for _ in range(count)]
    return _random_value_for_type(data_type)


def _random_value_for_type(data_type: str) -> Any:
    """Generate a random value for a given data type."""
    if data_type == "U1":
        return random.randint(0, 255)
    elif data_type == "I1":
        return random.randint(-128, 127)
    elif data_type == "X1":
        return random.randint(0, 255)
    elif data_type == "U2":
        return random.randint(0, 65535)
    elif data_type == "I2":
        return random.randint(-32768, 32767)
    elif data_type == "X2":
        return random.randint(0, 65535)
    elif data_type == "U4":
        return random.randint(0, 0xFFFFFFFF)
    elif data_type == "I4":
        return random.randint(-0x80000000, 0x7FFFFFFF)
    elif data_type == "X4":
        return random.randint(0, 0xFFFFFFFF)
    elif data_type == "R4":
        return random.uniform(-1000.0, 1000.0)
    elif data_type == "R8":
        return random.uniform(-1000000.0, 1000000.0)
    elif data_type == "CH":
        return chr(random.randint(65, 90))  # A-Z
    else:
        return 0


def encode_field(value: Any, data_type) -> bytes:
    """Encode a single field value to bytes."""
    # Handle data_type being a dict (e.g., array_of definitions)
    if isinstance(data_type, dict):
        if "array_of" in data_type:
            base_type = data_type["array_of"]
            # Handle nested structures - can't encode them, return empty
            if isinstance(base_type, dict):
                return b""
            count = data_type.get("count", 1)
            # Handle variable count (string like 'N' or count_field) - encode actual values provided
            if not isinstance(count, int):
                if isinstance(value, (list, tuple)):
                    count = len(value)
                elif isinstance(value, str):
                    count = len(value)
                else:
                    return b""  # No data for variable-length with no value
            if base_type == "CH":
                if isinstance(value, str):
                    encoded = value.encode("ascii", errors="replace")
                    return encoded[:count].ljust(count, b"\x00")
                return b"\x00" * count
            else:
                fmt, size = DATA_TYPE_MAP.get(base_type, ("B", 1))
                result = b""
                if isinstance(value, (list, tuple)):
                    for i in range(count):
                        v = value[i] if i < len(value) else 0
                        result += struct.pack(f"<{fmt}", v)
                else:
                    result = b"\x00" * (size * count)
                return result
        # Handle complex element structures
        if "elements" in data_type or "num_elements_field" in data_type:
            return b""
        data_type = data_type.get("type", "U1")
    
    if not isinstance(data_type, str):
        data_type = "U1"  # Fallback
    
    # Handle array types
    if "[" in data_type:
        base_type = data_type.split("[")[0]
        count_str = data_type.split("[")[1].rstrip("]")

        # Handle variable-length arrays like "U1[]"
        if not count_str:
            if isinstance(value, (list, tuple)):
                count = len(value)
            elif isinstance(value, str):
                count = len(value)
            else:
                return b""
        else:
            try:
                count = int(count_str)
            except ValueError:
                # Variable count like "U1[N]"
                if isinstance(value, (list, tuple)):
                    count = len(value)
                else:
                    return b""

        if base_type == "CH":
            # String/character array
            if isinstance(value, str):
                encoded = value.encode("ascii", errors="replace")
                # Pad or truncate to exact size
                return encoded[:count].ljust(count, b"\x00")
            return b"\x00" * count
        else:
            # Numeric array
            fmt, size = DATA_TYPE_MAP.get(base_type, ("B", 1))
            result = b""
            if isinstance(value, (list, tuple)):
                for i in range(count):
                    v = value[i] if i < len(value) else 0
                    result += struct.pack(f"<{fmt}", v)
            else:
                result = b"\x00" * (size * count)
            return result
    
    # Single value
    fmt, size = DATA_TYPE_MAP.get(data_type, ("B", 1))
    try:
        return struct.pack(f"<{fmt}", value)
    except struct.error:
        return b"\x00" * size


def generate_ubx_message(message: dict, field_values: Optional[dict] = None, variant_name: Optional[str] = None) -> bytes:
    """Generate a complete UBX binary message from schema and field values.

    Args:
        message: Message definition from schema
        field_values: Optional dict of field name -> value. Missing fields use defaults.
        variant_name: Optional variant name for multi-variant messages

    Returns:
        Complete UBX message as bytes (sync + class + id + length + payload + checksum)
    """
    if field_values is None:
        field_values = generate_test_values(message, variant_name=variant_name)

    # Get class and message IDs
    class_id = parse_hex_id(message.get("class_id", 0))
    msg_id = parse_hex_id(message.get("message_id", 0))

    # Get payload definition (handles variants)
    payload, variant = get_message_payload(message, variant_name)

    # If generating a variant, ensure discriminator value is set
    if variant and "discriminator" in variant:
        disc = variant["discriminator"]
        if "field" in disc and "value" in disc:
            if disc["field"] not in field_values:
                field_values[disc["field"]] = disc["value"]
    fields = payload.get("fields", [])
    
    # Sort fields by byte_offset to ensure correct order
    # Handle fields with None or non-integer byte_offsets by putting them at the end
    def get_sort_key(f):
        offset = f.get("byte_offset")
        if isinstance(offset, int):
            return (0, offset)  # Integer offsets first, sorted by value
        return (1, 0)  # Non-integer offsets (None, strings) at the end
    sorted_fields = sorted(fields, key=get_sort_key)
    
    # Build payload bytes
    payload_bytes = bytearray()
    current_offset = 0
    
    for field in sorted_fields:
        name = field.get("name")
        data_type = field.get("data_type", "U1")
        byte_offset = field.get("byte_offset")

        # Skip fields with non-integer byte_offsets (variable position fields)
        if not isinstance(byte_offset, int):
            continue

        # Pad if there's a gap
        if byte_offset > current_offset:
            payload_bytes.extend(b"\x00" * (byte_offset - current_offset))
            current_offset = byte_offset
        
        # Get value (use provided or default to 0)
        value = field_values.get(name, 0)
        
        # Encode field
        encoded = encode_field(value, data_type)
        payload_bytes.extend(encoded)
        current_offset += len(encoded)
    
    # Encode repeated groups
    repeated_groups = payload.get("repeated_groups", [])
    rg_values = field_values.get("_repeated_groups", {})
    
    for rg in repeated_groups:
        rg_name = rg.get("name", "group")
        rg_fields = rg.get("fields", [])
        base_offset = rg.get("base_offset", current_offset)
        
        # Handle dynamic base_offset (v1.3 format)
        if isinstance(base_offset, dict):
            # Compute: base + sum(field_value * multiplier)
            computed = base_offset.get("base", 0)
            for term in base_offset.get("add_field_products", []):
                field_name = term.get("field")
                multiplier = term.get("multiplier", 1)
                field_value = field_values.get(field_name, 0)
                computed += field_value * multiplier
            base_offset = computed
        elif not isinstance(base_offset, int):
            # Legacy string formula - use current_offset
            base_offset = current_offset
        
        # Pad to base_offset if needed
        if base_offset > current_offset:
            payload_bytes.extend(b"\x00" * (base_offset - current_offset))
            current_offset = base_offset
        
        # Get instances for this group
        instances = rg_values.get(rg_name, [])
        
        for instance in instances:
            # Sort fields by byte_offset within the group
            def get_rg_sort_key(f):
                offset = f.get("byte_offset")
                if isinstance(offset, int):
                    return (0, offset)
                return (1, 0)
            sorted_rg_fields = sorted(rg_fields, key=get_rg_sort_key)
            group_start = current_offset
            
            for field in sorted_rg_fields:
                fname = field.get("name")
                ftype = field.get("data_type", "U1")
                foffset = field.get("byte_offset", 0)
                
                # Absolute offset within this instance
                abs_offset = group_start + foffset
                if abs_offset > current_offset:
                    payload_bytes.extend(b"\x00" * (abs_offset - current_offset))
                    current_offset = abs_offset
                
                value = instance.get(fname, 0)
                encoded = encode_field(value, ftype)
                payload_bytes.extend(encoded)
                current_offset += len(encoded)
            
            # Pad to group_size_bytes if specified
            group_size = rg.get("group_size_bytes")
            if group_size:
                expected_end = group_start + group_size
                if current_offset < expected_end:
                    payload_bytes.extend(b"\x00" * (expected_end - current_offset))
                    current_offset = expected_end
    
    # Build message
    payload_len = len(payload_bytes)
    
    # Header: class, id, length (little-endian)
    header = bytes([class_id, msg_id]) + struct.pack("<H", payload_len)
    
    # Calculate checksum over class, id, length, and payload
    checksum_data = header + bytes(payload_bytes)
    ck_a, ck_b = calculate_checksum(checksum_data)
    
    # Complete message
    return bytes([SYNC_CHAR_1, SYNC_CHAR_2]) + checksum_data + bytes([ck_a, ck_b])
