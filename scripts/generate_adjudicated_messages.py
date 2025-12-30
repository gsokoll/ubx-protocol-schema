#!/usr/bin/env python3
"""Generate validated JSON files for adjudicated no-consensus messages.

This script reads protocol_notes.json and generates canonical validated JSON
files for messages that couldn't reach consensus through majority voting,
but have been manually adjudicated.

The canonical source is selected based on:
1. explicit canonical_source in protocol_notes.json
2. first entry in newer_manuals list (prefer latest firmware)

Usage:
    uv run python scripts/generate_adjudicated_messages.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def find_extraction_file(manual_hint: str, extractions_dir: Path) -> Path | None:
    """Find extraction file matching a manual hint."""
    for f in extractions_dir.glob("*_anthropic.json"):
        if manual_hint.replace("-", "").lower() in f.stem.replace("-", "").lower():
            return f
    return None


def get_message_from_extraction(extraction_file: Path, message_name: str) -> dict | None:
    """Get a specific message from an extraction file."""
    data = json.loads(extraction_file.read_text())
    for msg in data.get("messages", []):
        if msg.get("name") == message_name:
            return msg
    return None


def create_validated_json(
    message: dict,
    protocol_version: int,
    note: dict,
    source_file: str,
) -> dict:
    """Create validated JSON structure with annotations."""
    
    # Get fields from message
    fields = message.get("fields", [])
    if not fields and message.get("payload"):
        fields = message["payload"].get("fields", [])
    
    # Build annotation from protocol note
    annotation = {
        "type": "evolution",
        "severity": "info",
        "issue": note.get("issue", "Protocol evolution without version bump"),
        "details": note.get("details", ""),
        "affected_offset": note.get("affected_field", {}).get("offset"),
        "recommendation": note.get("recommendation", ""),
    }
    
    validated = {
        "name": message.get("name"),
        "protocol_version": protocol_version,
        "class_id": message.get("class_id"),
        "message_id": message.get("message_id"),
        "description": message.get("description"),
        "adjudicated": {
            "source": source_file,
            "reason": "Manual adjudication - no consensus due to protocol evolution",
            "adjudication_date": datetime.now().strftime("%Y-%m-%d"),
            "older_manuals": note.get("older_manuals", []),
            "newer_manuals": note.get("newer_manuals", []),
        },
        "annotations": [annotation],
        "fields": fields,
    }
    
    # Add payload length if available
    if message.get("payload", {}).get("length"):
        validated["payload_length"] = message["payload"]["length"]
    
    return validated


def generate_filename(message_name: str, protocol_version: int) -> str:
    """Generate filename for validated message."""
    name = message_name.replace("UBX-", "")
    return f"{name}-v{protocol_version}.json"


def main():
    extractions_dir = PROJECT_ROOT / "data" / "by-manual"
    validated_dir = PROJECT_ROOT / "data" / "validated" / "messages"
    protocol_notes_file = PROJECT_ROOT / "data" / "validated" / "protocol_notes.json"
    
    if not protocol_notes_file.exists():
        print("Error: protocol_notes.json not found")
        return 1
    
    notes = json.loads(protocol_notes_file.read_text())
    
    print("Generating validated JSON for adjudicated messages:")
    print()
    
    for note in notes.get("notes", []):
        message_name = note.get("message")
        protocol_version = note.get("protocol_version", 0)
        
        # Find canonical source
        canonical_source = note.get("canonical_source")
        if not canonical_source:
            newer_manuals = note.get("newer_manuals", [])
            if newer_manuals:
                canonical_source = newer_manuals[-1]  # Last is usually latest
        
        if not canonical_source:
            print(f"  {message_name} v{protocol_version}: No canonical source specified")
            continue
        
        # Find extraction file
        extraction_file = find_extraction_file(canonical_source, extractions_dir)
        if not extraction_file:
            print(f"  {message_name} v{protocol_version}: Extraction file not found for {canonical_source}")
            continue
        
        # Get message from extraction
        message = get_message_from_extraction(extraction_file, message_name)
        if not message:
            print(f"  {message_name} v{protocol_version}: Message not found in {extraction_file.name}")
            continue
        
        # Create validated JSON
        validated = create_validated_json(
            message=message,
            protocol_version=protocol_version,
            note=note,
            source_file=extraction_file.stem,
        )
        
        # Write to file
        filename = generate_filename(message_name, protocol_version)
        output_path = validated_dir / filename
        output_path.write_text(json.dumps(validated, indent=2))
        
        fields_count = len(validated.get("fields", []))
        print(f"  ✅ {message_name} v{protocol_version}: {fields_count} fields -> {filename}")
        print(f"     Source: {canonical_source}")
    
    print()
    print("Done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
