#!/usr/bin/env python3
"""Generate a schema-compliant UBX message collection from adjudicated results.

Outputs a single JSON file with all messages conforming to ubx-message-schema-v1.4.json.

Key features:
- Loads manual metadata to get protocol versions for each source manual
- Extracts source manuals from adjudication extraction_verdicts
- Populates supported_versions with protocol version integers and source manuals
"""

import argparse
import json
import re
from pathlib import Path
from datetime import datetime


def parse_offset_formula(formula: str) -> dict:
    """Convert a string formula like '96 + nValA * 8' to machine-readable format.
    
    Returns:
        {"base": int, "add_field_products": [{"field": str, "multiplier": int}, ...]}
    """
    result = {"base": 0, "add_field_products": []}
    
    # Clean up the formula
    formula = formula.replace(" ", "")
    
    # Pattern for terms: number, or field*number, or number*field
    # Split on + signs
    terms = formula.split("+")
    
    for term in terms:
        term = term.strip()
        if not term:
            continue
        
        # Check if it's a simple integer
        if re.match(r'^-?\d+$', term):
            result["base"] += int(term)
        # Check for field*number pattern
        elif '*' in term:
            parts = term.split('*')
            if len(parts) == 2:
                # Determine which is the field and which is the number
                if re.match(r'^-?\d+$', parts[0]):
                    multiplier = int(parts[0])
                    field = parts[1]
                else:
                    field = parts[0]
                    multiplier = int(parts[1]) if re.match(r'^-?\d+$', parts[1]) else 1
                result["add_field_products"].append({"field": field, "multiplier": multiplier})
        else:
            # It's just a field name (multiplier of 1)
            result["add_field_products"].append({"field": term, "multiplier": 1})
    
    # If no products, just return the base as integer
    if not result["add_field_products"]:
        return result["base"]
    
    return result


def load_manual_metadata(metadata_file: Path) -> dict:
    """Load manual metadata containing protocol versions.
    
    Returns:
        Dict mapping manual_key -> {protocol_version: int, firmware_version: str, ...}
    """
    if not metadata_file.exists():
        print(f"Warning: Manual metadata file not found: {metadata_file}")
        return {}
    
    data = json.loads(metadata_file.read_text())
    return data.get("manuals", {})


def extract_source_manuals(adjudication_data: dict) -> list[str]:
    """Extract list of source manual keys from adjudication data.
    
    Looks for extraction_verdicts in the adjudication section.
    """
    sources = []
    adjudication = adjudication_data.get("adjudication", {})
    
    # Handle case where adjudication is a list
    if isinstance(adjudication, list):
        adjudication = adjudication[0] if adjudication else {}
    
    # Get extraction verdicts
    verdicts = adjudication.get("extraction_verdicts", [])
    for verdict in verdicts:
        source = verdict.get("source", "")
        if source and source not in sources:
            sources.append(source)
    
    return sources


def build_supported_versions(source_manuals: list[str], manual_metadata: dict) -> dict | None:
    """Build supported_versions object from source manuals and metadata.
    
    Returns:
        Dict with protocol_versions (sorted list of ints), min_protocol_version, source_manuals
        or None if no protocol versions found
    """
    protocol_versions = set()
    
    for manual_key in source_manuals:
        if manual_key in manual_metadata:
            pv = manual_metadata[manual_key].get("protocol_version")
            if pv:
                protocol_versions.add(pv)
    
    if not protocol_versions:
        return None
    
    sorted_versions = sorted(protocol_versions)
    return {
        "protocol_versions": sorted_versions,
        "min_protocol_version": sorted_versions[0],
        "source_manuals": source_manuals,
    }


def generate_collection(adjudicated_dir: Path, output_file: Path, metadata_file: Path | None = None):
    """Generate schema-compliant message collection from adjudicated results."""
    
    # Load manual metadata for protocol version lookup
    if metadata_file is None:
        metadata_file = adjudicated_dir.parent.parent / "data" / "manual_metadata.json"
    manual_metadata = load_manual_metadata(metadata_file)
    print(f"Loaded metadata for {len(manual_metadata)} manuals")
    
    adjudicated_files = sorted(adjudicated_dir.glob("*.json"))
    print(f"Found {len(adjudicated_files)} adjudicated messages")
    
    messages = []
    errors = 0
    
    for adj_file in adjudicated_files:
        try:
            data = json.loads(adj_file.read_text())
            msg_name = data.get("message_name", adj_file.stem)
            adjudication = data.get("adjudication", {})
            
            # Handle case where adjudication is a list
            if isinstance(adjudication, list):
                adjudication = adjudication[0] if adjudication else {}
            
            canonical = adjudication.get("canonical_structure")
            if not canonical:
                print(f"  {msg_name}: SKIP - no canonical structure")
                errors += 1
                continue
            
            # Handle case where canonical_structure is a string or list
            if isinstance(canonical, str):
                print(f"  {msg_name}: SKIP - canonical_structure is string")
                errors += 1
                continue
            if isinstance(canonical, list):
                canonical = canonical[0] if canonical else {}
            if not isinstance(canonical, dict):
                print(f"  {msg_name}: SKIP - canonical_structure not dict")
                errors += 1
                continue
            
            # Unwrap ubx_message if present (Gemini output variation)
            if "ubx_message" in canonical and isinstance(canonical["ubx_message"], dict):
                canonical = canonical["ubx_message"]
            
            # Validate required fields per schema
            message = {}
            
            # Required: name
            message["name"] = canonical.get("name", msg_name)
            
            # Required: class_id (handle Gemini output variations)
            class_id = (canonical.get("class_id") or canonical.get("ubx_class") or 
                        canonical.get("classId") or canonical.get("message_class") or
                        canonical.get("message_class_id") or canonical.get("class"))
            if not class_id:
                print(f"  {msg_name}: SKIP - no class_id")
                errors += 1
                continue
            message["class_id"] = class_id
            
            # Required: message_id (handle Gemini output variations)
            message_id = (canonical.get("message_id") or canonical.get("ubx_id") or 
                          canonical.get("messageId") or canonical.get("msg_id") or
                          canonical.get("id"))
            if not message_id:
                print(f"  {msg_name}: SKIP - no message_id")
                errors += 1
                continue
            message["message_id"] = message_id
            
            # Required: message_type
            message_type = canonical.get("message_type", "output")
            # Normalize to valid enum values
            type_map = {
                "output": "output",
                "input": "input",
                "command": "command",
                "set": "set",
                "get": "get",
                "get/set": "get_set",
                "get_set": "get_set",
                "poll": "poll_request",
                "poll_request": "poll_request",
                "polled": "polled",
                "periodic": "periodic",
                "periodic/polled": "periodic_polled",
                "periodic_polled": "periodic_polled",
                "input/output": "input_output",
                "input_output": "input_output",
            }
            message["message_type"] = type_map.get(message_type.lower(), "output")
            
            # Optional: description
            if canonical.get("description"):
                message["description"] = canonical["description"]
            
            # Payload - normalize structure (handle fields at wrong level)
            payload = canonical.get("payload", {})
            
            # Handle case where payload is a list of fields directly (Gemini output variation)
            if isinstance(payload, list):
                payload = {
                    "length": canonical.get("payload_length", {}),
                    "fields": payload,
                    "repeated_groups": []
                }
            
            # If payload is empty but fields exist at top level, normalize
            if not payload.get("fields") and canonical.get("fields"):
                payload = {
                    "length": canonical.get("length", {}),
                    "fields": canonical.get("fields", []),
                    "repeated_groups": canonical.get("repeated_groups", [])
                }
            
            # Handle payload_fields at root level (Gemini output variation)
            if not payload.get("fields") and canonical.get("payload_fields"):
                payload = {
                    "length": canonical.get("payload_length", {}),
                    "fields": canonical.get("payload_fields", []),
                    "repeated_groups": canonical.get("repeated_groups", [])
                }
            
            # Handle payload_structure at root level (Gemini output variation)
            if not payload.get("fields") and canonical.get("payload_structure"):
                payload = {
                    "length": canonical.get("length_bytes", canonical.get("payload_length", {})),
                    "fields": canonical.get("payload_structure", []),
                    "repeated_groups": canonical.get("repeated_groups", [])
                }
            if payload or canonical.get("fields"):
                schema_payload = {}
                
                # Length (required in payload)
                length = payload.get("length", {})
                if isinstance(length, dict):
                    if "fixed" in length:
                        schema_payload["length"] = {"fixed": length["fixed"]}
                    elif "variable" in length:
                        schema_payload["length"] = {"variable": length["variable"]}
                    elif "min" in length or "max" in length:
                        var_length = {"base": length.get("min", 0)}
                        if length.get("min") is not None:
                            var_length["min"] = length["min"]
                        if length.get("max") is not None:
                            var_length["max"] = length["max"]
                        schema_payload["length"] = {"variable": var_length}
                    else:
                        schema_payload["length"] = {"fixed": 0}
                elif isinstance(length, list):
                    # Handle list of valid lengths like [8, 40] - treat as variable with min/max
                    sorted_lengths = sorted(length)
                    schema_payload["length"] = {"variable": {"min": sorted_lengths[0], "max": sorted_lengths[-1]}}
                elif isinstance(length, str):
                    # Handle string formula like "4 + 4*N"
                    schema_payload["length"] = {"variable": {"base": 0, "formula": length}}
                else:
                    schema_payload["length"] = {"fixed": int(length) if length else 0}
                
                # Fields (required in payload)
                fields = payload.get("fields", [])
                schema_fields = []
                for field in fields:
                    if not isinstance(field, dict):
                        continue
                    schema_field = {}
                    
                    # Required: name
                    if not field.get("name"):
                        continue
                    schema_field["name"] = field["name"]
                    
                    # Required: byte_offset
                    byte_offset = field.get("byte_offset")
                    if byte_offset is None:
                        byte_offset = field.get("offset", 0)
                    schema_field["byte_offset"] = byte_offset
                    
                    # Required: data_type (handle Gemini variations: type, dataType)
                    data_type = field.get("data_type") or field.get("type") or field.get("dataType") or "U1"
                    schema_field["data_type"] = data_type
                    
                    # Preserve fixed_value if already set, or extract from description
                    # Patterns: "(0x01 for this type)", "(0x02)", "0x01 for this version"
                    description = field.get("description", "")
                    if "fixed_value" in field:
                        schema_field["fixed_value"] = field["fixed_value"]
                    elif field["name"] == "type" and byte_offset == 0:
                        import re
                        # Try multiple patterns for type discriminator values
                        # Pattern 1: "(0x01 for this type/version)"
                        match = re.search(r'\(0x([0-9a-fA-F]+)\s+for\s+this\s+(?:type|version)\)', description)
                        if not match:
                            # Pattern 2: "(0x01)" standalone
                            match = re.search(r'\(0x([0-9a-fA-F]+)\)', description)
                        if not match:
                            # Pattern 3: "(0x01 for MESSAGE-NAME)"
                            match = re.search(r'\(0x([0-9a-fA-F]+)\s+for\s+\w', description)
                        if match:
                            schema_field["fixed_value"] = int(match.group(1), 16)
                    
                    # Optional fields
                    if description:
                        schema_field["description"] = description
                    if field.get("unit"):
                        schema_field["unit"] = field["unit"]
                    if field.get("scale"):
                        schema_field["scale"] = field["scale"]
                    if field.get("reserved"):
                        schema_field["reserved"] = True
                    if field.get("bitfield"):
                        schema_field["bitfield"] = field["bitfield"]
                    if field.get("enumeration"):
                        schema_field["inline_enum"] = field["enumeration"]
                    
                    schema_fields.append(schema_field)
                
                schema_payload["fields"] = schema_fields
                
                # Repeated groups - convert string formulas to machine-readable format
                repeated_groups = payload.get("repeated_groups", [])
                if payload.get("repeated_block"):
                    repeated_groups = [payload["repeated_block"]]
                
                if repeated_groups:
                    processed_groups = []
                    for rg in repeated_groups:
                        rg = dict(rg)  # Copy to avoid modifying original
                        base_offset = rg.get("base_offset")
                        if isinstance(base_offset, str):
                            # Convert string formula to machine-readable format
                            rg["base_offset"] = parse_offset_formula(base_offset)
                        processed_groups.append(rg)
                    schema_payload["repeated_groups"] = processed_groups
                
                message["payload"] = schema_payload
            
            # Add supported_versions with protocol version information
            source_manuals = extract_source_manuals(data)
            supported_versions = build_supported_versions(source_manuals, manual_metadata)
            if supported_versions:
                message["supported_versions"] = supported_versions
            
            # Add metadata as comment
            confidence = adjudication.get("canonical_confidence", "unknown")
            num_sources = data.get("num_extractions", 0)
            message["comment"] = f"Confidence: {confidence}, Sources: {num_sources}"
            
            messages.append(message)
            pv_info = f", ProtVer: {supported_versions['min_protocol_version']}-{supported_versions['protocol_versions'][-1]}" if supported_versions else ""
            print(f"  {msg_name}: OK{pv_info}")
            
        except Exception as e:
            print(f"  {adj_file.stem}: ERROR - {e}")
            errors += 1
    
    # Build collection
    collection = {
        "schema_version": "1.4",
        "generated": datetime.now().isoformat(),
        "messages": messages
    }
    
    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(collection, indent=2))
    
    print(f"\n=== Summary ===")
    print(f"  Messages: {len(messages)}")
    print(f"  Errors: {errors}")
    print(f"  Output: {output_file}")
    
    return len(messages), errors


def main():
    parser = argparse.ArgumentParser(description="Generate schema-compliant message collection")
    parser.add_argument("--adjudicated-dir", type=Path, default=Path("_working/stage3_adjudication"),
                        help="Directory with adjudicated results")
    parser.add_argument("--output", type=Path, default=Path("data/messages/ubx_messages.json"),
                        help="Output collection file")
    
    args = parser.parse_args()
    generate_collection(args.adjudicated_dir, args.output)


if __name__ == "__main__":
    main()
