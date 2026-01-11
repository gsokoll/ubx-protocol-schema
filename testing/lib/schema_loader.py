"""Load and query the UBX message schema."""

import json
from pathlib import Path
from typing import Optional

# Cache for loaded schema
_schema_cache: Optional[dict] = None


def load_schema(schema_path: Optional[Path] = None) -> dict:
    """Load the UBX message schema from JSON file."""
    global _schema_cache
    
    if _schema_cache is not None:
        return _schema_cache
    
    if schema_path is None:
        # Default path relative to this file
        schema_path = Path(__file__).parent.parent.parent / "data" / "messages" / "ubx_messages.json"
    
    with open(schema_path) as f:
        _schema_cache = json.load(f)
    
    return _schema_cache


def get_message_by_name(name: str) -> Optional[dict]:
    """Get message definition by name (e.g., 'UBX-NAV-PVT').

    Also searches variant_aliases for backward compatibility with legacy names
    like 'UBX-MGA-GPS-EPH'.
    """
    schema = load_schema()
    for msg in schema.get("messages", []):
        if msg.get("name") == name:
            return msg
        # Check variant_aliases for backward compatibility
        if name in msg.get("variant_aliases", []):
            return msg
    return None


def get_variant_by_alias(alias: str) -> Optional[tuple[dict, dict]]:
    """Get a specific variant by its alias name.

    Args:
        alias: Legacy variant name (e.g., 'UBX-MGA-GPS-EPH')

    Returns:
        Tuple of (message, variant) if found, None otherwise.
        The variant dict contains the specific payload for this variant.
    """
    schema = load_schema()
    for msg in schema.get("messages", []):
        if alias not in msg.get("variant_aliases", []):
            continue

        # Found the parent message, now find the matching variant
        base_name = msg.get("name")  # e.g., "UBX-MGA-GPS"
        suffix = alias[len(base_name):]  # e.g., "-EPH"
        variant_name = suffix.lstrip("-")  # e.g., "EPH"

        for variant in msg.get("variants", []):
            if variant.get("name") == variant_name:
                return (msg, variant)

    return None


def select_variant_by_payload(msg: dict, payload: bytes) -> Optional[dict]:
    """Select the correct variant based on payload content.

    Uses the discriminator field to determine which variant matches.

    Args:
        msg: Message definition with variants
        payload: Raw payload bytes

    Returns:
        The matching variant dict, or None if no match.
    """
    variants = msg.get("variants", [])
    if not variants:
        return None

    for variant in variants:
        disc = variant.get("discriminator", {})

        # Check by payload length
        if "payload_length" in disc:
            if len(payload) == disc["payload_length"]:
                return variant

        # Check by payload length range
        if "payload_length_range" in disc:
            range_spec = disc["payload_length_range"]
            min_len = range_spec.get("min", 0)
            max_len = range_spec.get("max")
            if len(payload) >= min_len and (max_len is None or len(payload) <= max_len):
                return variant

        # Check by field value
        if "field" in disc and "byte_offset" in disc and "value" in disc:
            offset = disc["byte_offset"]
            expected = disc["value"]
            if offset < len(payload):
                actual = payload[offset]
                if actual == expected:
                    return variant

    return None


def get_message_by_ids(class_id: int, message_id: int) -> Optional[dict]:
    """Get message definition by class and message IDs."""
    schema = load_schema()
    for msg in schema.get("messages", []):
        msg_class = msg.get("class_id")
        msg_id = msg.get("message_id")
        
        # Handle hex string or int
        if isinstance(msg_class, str):
            msg_class = int(msg_class, 16)
        if isinstance(msg_id, str):
            msg_id = int(msg_id, 16)
        
        if msg_class == class_id and msg_id == message_id:
            return msg
    return None


def get_all_messages() -> list:
    """Get all message definitions."""
    schema = load_schema()
    return schema.get("messages", [])


def parse_hex_id(value) -> int:
    """Parse a hex string or int to int."""
    if isinstance(value, str):
        return int(value, 16)
    return int(value)
