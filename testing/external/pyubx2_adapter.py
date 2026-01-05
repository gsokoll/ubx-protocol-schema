"""Adapter for pyubx2 library to enable cross-validation testing."""

from typing import Any, Optional

try:
    from pyubx2 import UBXReader, UBXMessage, GET, SET, POLL
    from pyubx2.ubxtypes_core import UBX_MSGIDS
    from pyubx2.ubxtypes_get import UBX_PAYLOADS_GET
    from pyubx2.ubxtypes_set import UBX_PAYLOADS_SET
    from pyubx2.ubxtypes_poll import UBX_PAYLOADS_POLL
    PYUBX2_AVAILABLE = True
except ImportError:
    PYUBX2_AVAILABLE = False
    UBXReader = None
    UBXMessage = None


def is_available() -> bool:
    """Check if pyubx2 is installed and available."""
    return PYUBX2_AVAILABLE


def get_supported_messages() -> list[str]:
    """Get list of message names supported by pyubx2."""
    if not PYUBX2_AVAILABLE:
        return []
    
    messages = set()
    for msg_id, name in UBX_MSGIDS.items():
        # Convert "ACK-ACK" to "UBX-ACK-ACK" format
        if not name.startswith("UBX-"):
            name = f"UBX-{name}"
        messages.add(name)
    
    return sorted(messages)


def parse_ubx_bytes(data: bytes, message_type: str = "output") -> Optional[dict]:
    """Parse UBX bytes using pyubx2.
    
    Args:
        data: Raw UBX message bytes
        message_type: Our schema's message_type to determine pyubx2 mode
    
    Returns:
        Dict with parsed message info, or None if parsing failed
    """
    if not PYUBX2_AVAILABLE:
        raise RuntimeError("pyubx2 is not installed")
    
    # Map our message_type to pyubx2 mode
    mode_map = {
        "output": GET,
        "input": SET,
        "command": SET,
        "set": SET,
        "get": GET,
        "get_set": GET,
        "poll_request": POLL,
        "polled": GET,
        "periodic": GET,
        "periodic_polled": GET,
        "input_output": GET,
    }
    mode = mode_map.get(message_type, GET)
    
    try:
        from io import BytesIO
        stream = BytesIO(data)
        reader = UBXReader(stream, msgmode=mode)
        raw, parsed = reader.read()
        
        if parsed is None:
            return {"error": "pyubx2 returned None (unknown message or mode)", "parsed": False}
        
        # Extract field values
        fields = {}
        for attr in dir(parsed):
            if not attr.startswith("_") and attr not in ("identity", "msg_cls", "msg_id", "length", "payload"):
                try:
                    value = getattr(parsed, attr)
                    if not callable(value):
                        fields[attr] = value
                except:
                    pass
        
        return {
            "name": parsed.identity,
            "class_id": parsed.msg_cls[0] if isinstance(parsed.msg_cls, bytes) else parsed.msg_cls,
            "message_id": parsed.msg_id[0] if isinstance(parsed.msg_id, bytes) else parsed.msg_id,
            "payload_length": parsed.length,
            "fields": fields,
            "parsed": True,
        }
    except Exception as e:
        return {"error": str(e), "parsed": False}


def generate_ubx_message(msg_name: str, field_values: dict) -> Optional[bytes]:
    """Generate a UBX message using pyubx2.
    
    Args:
        msg_name: Message name (e.g., "NAV-PVT" or "UBX-NAV-PVT")
        field_values: Dict of field name -> value
    
    Returns:
        Raw UBX message bytes, or None if generation failed
    """
    if not PYUBX2_AVAILABLE:
        raise RuntimeError("pyubx2 is not installed")
    
    # Normalize name
    if msg_name.startswith("UBX-"):
        msg_name = msg_name[4:]  # Remove "UBX-" prefix
    
    # Parse class-id from name
    parts = msg_name.split("-")
    if len(parts) < 2:
        return None
    
    msg_class = parts[0]
    msg_id = "-".join(parts[1:])
    
    try:
        # Determine message mode (GET for output messages)
        msg = UBXMessage(msg_class, msg_id, GET, **field_values)
        return msg.serialize()
    except Exception as e:
        # Try SET mode
        try:
            msg = UBXMessage(msg_class, msg_id, SET, **field_values)
            return msg.serialize()
        except:
            return None


def get_message_definition(msg_name: str) -> Optional[dict]:
    """Get pyubx2's definition for a message.
    
    Args:
        msg_name: Message name (e.g., "NAV-PVT")
    
    Returns:
        Dict with field definitions, or None if not found
    """
    if not PYUBX2_AVAILABLE:
        return None
    
    # Normalize name
    if msg_name.startswith("UBX-"):
        msg_name = msg_name[4:]
    
    # Look up in payload definitions
    for payloads in [UBX_PAYLOADS_GET, UBX_PAYLOADS_SET, UBX_PAYLOADS_POLL]:
        if msg_name in payloads:
            return {
                "name": msg_name,
                "fields": payloads[msg_name],
            }
    
    return None


def compare_field_definitions(our_msg: dict, pyubx2_name: str) -> dict:
    """Compare our field definitions with pyubx2's.
    
    Args:
        our_msg: Our message definition
        pyubx2_name: Message name in pyubx2 format
    
    Returns:
        Comparison result with matches and discrepancies
    """
    if not PYUBX2_AVAILABLE:
        return {"error": "pyubx2 not available"}
    
    pyubx2_def = get_message_definition(pyubx2_name)
    if pyubx2_def is None:
        return {"error": f"Message {pyubx2_name} not found in pyubx2"}
    
    our_fields = {f["name"]: f for f in our_msg.get("payload", {}).get("fields", [])}
    pyubx2_fields = pyubx2_def.get("fields", {})
    
    matches = []
    our_only = []
    pyubx2_only = []
    type_mismatches = []
    
    # Compare fields
    for name, our_field in our_fields.items():
        if name in pyubx2_fields:
            matches.append(name)
            # Could compare types here too
        else:
            our_only.append(name)
    
    for name in pyubx2_fields:
        if name not in our_fields:
            pyubx2_only.append(name)
    
    return {
        "matches": matches,
        "our_only": our_only,
        "pyubx2_only": pyubx2_only,
        "type_mismatches": type_mismatches,
        "match_ratio": len(matches) / max(len(our_fields), 1),
    }
