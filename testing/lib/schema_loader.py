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
    """Get message definition by name (e.g., 'UBX-NAV-PVT')."""
    schema = load_schema()
    for msg in schema.get("messages", []):
        if msg.get("name") == name:
            return msg
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
