#!/usr/bin/env python3
"""Merge and deduplicate config keys from multiple manual extractions.

Creates a unified config key database with version tracking.
"""

import argparse
import json
import re
from pathlib import Path
from collections import defaultdict


def parse_scale_to_object(scale_str: str) -> dict | None:
    """Convert scale string to schema-compliant object with raw and multiplier."""
    if not scale_str or scale_str == '-' or scale_str == 'None':
        return None
    
    # Try to parse as number
    try:
        multiplier = float(scale_str)
    except ValueError:
        # Handle special formats like "2^-7"
        match = re.match(r'(\d+)\^(-?\d+)', scale_str)
        if match:
            base, exp = int(match.group(1)), int(match.group(2))
            multiplier = base ** exp
        else:
            return None
    
    result = {"raw": scale_str, "multiplier": multiplier}
    
    # Add representation info for common formats
    if 'e' in scale_str.lower():
        match = re.match(r'1e(-?\d+)', scale_str.lower())
        if match:
            result["representation"] = {
                "type": "power_of_10",
                "base": 10,
                "exponent": int(match.group(1))
            }
    elif '^' in scale_str:
        match = re.match(r'(\d+)\^(-?\d+)', scale_str)
        if match:
            base, exp = int(match.group(1)), int(match.group(2))
            result["representation"] = {
                "type": "power_of_2" if base == 2 else "power_of_10",
                "base": base,
                "exponent": exp
            }
    
    return result


def make_schema_compliant(keys: list[dict]) -> tuple[dict, list[dict]]:
    """Transform keys to be schema-compliant.
    
    Returns:
        (groups_dict, keys_list) - both schema-compliant
    """
    groups = {}
    compliant_keys = []
    
    for key in keys:
        name = key.get('name', '')
        key_id = key.get('key_id', '')
        
        # 1. Fix key_id format - ensure 8 hex digits
        if key_id.startswith('0x') and len(key_id) < 10:
            key_id = f"0x{key_id[2:].zfill(8)}"
            key['key_id'] = key_id
        
        # 2. Extract group from name: CFG-GROUP-ITEM -> CFG-GROUP
        parts = name.split('-')
        if len(parts) >= 3:
            group_name = f"{parts[0]}-{parts[1]}"
        else:
            group_name = parts[0] if parts else "UNKNOWN"
        
        # 3. Extract group_id and item_id from key_id
        try:
            key_id_int = int(key_id, 16)
            group_id_int = (key_id_int >> 16) & 0xFF
            item_id_int = key_id_int & 0xFFFF
            group_id = f"0x{group_id_int:02x}"
            item_id = f"0x{item_id_int:04x}"
        except ValueError:
            group_id = "0x00"
            item_id = "0x0000"
        
        # Build groups dict
        if group_name not in groups:
            groups[group_name] = {
                "name": group_name,
                "group_id": group_id
            }
        
        # Add required fields to key
        key['group'] = group_name
        key['item_id'] = item_id
        
        # 4. Convert scale string to object
        if 'scale' in key:
            scale_val = key['scale']
            if isinstance(scale_val, str):
                parsed = parse_scale_to_object(scale_val)
                if parsed:
                    key['scale'] = parsed
                else:
                    del key['scale']
            elif scale_val is None:
                del key['scale']
        
        # 5. Remove None values from optional fields
        for field in ['unit', 'inline_enum', 'bitfield', 'scale']:
            if field in key and key[field] is None:
                del key[field]
        
        # 6. Clean up unit field
        if 'unit' in key:
            unit = key['unit']
            if unit in ('-', '', ' ', 'None', '1'):
                del key['unit']
        
        # 7. Fix inline_enum - ensure values dict has valid entries
        if 'inline_enum' in key:
            ie = key['inline_enum']
            if 'values' in ie:
                vals = ie['values']
                # Convert list format to dict if needed
                if isinstance(vals, list):
                    new_vals = {}
                    for item in vals:
                        if isinstance(item, dict) and 'name' in item:
                            new_vals[item['name']] = {
                                'value': item.get('value', 0),
                                'description': item.get('description', '')
                            }
                    ie['values'] = new_vals
                # Remove entries with None values
                ie['values'] = {
                    k: v for k, v in ie['values'].items() 
                    if v.get('value') is not None
                }
        
        # 8. Fix bitfield - ensure each bit entry has required fields
        if 'bitfield' in key:
            bf = key['bitfield']
            if 'bits' in bf and isinstance(bf['bits'], list):
                for bit in bf['bits']:
                    # Add default data_type if missing (U=unsigned is most common)
                    if 'data_type' not in bit:
                        bit['data_type'] = 'U'
                    # Ensure bit_start and bit_end are present
                    if 'bit_start' not in bit:
                        bit['bit_start'] = 0
                    if 'bit_end' not in bit:
                        bit['bit_end'] = bit.get('bit_start', 0)
        
        # 8. Remove internal fields not in schema (but keep 'sources')
        for field in ['source_count', '_sources']:
            if field in key:
                del key[field]

        # 9. Sort sources lists for consistent output
        if 'sources' in key and isinstance(key['sources'], list):
            key['sources'] = sorted(set(key['sources']))

        # 10. Sort sources in enum values too
        if 'inline_enum' in key and isinstance(key['inline_enum'].get('values'), dict):
            for val in key['inline_enum']['values'].values():
                if isinstance(val, dict) and 'sources' in val:
                    val['sources'] = sorted(set(val['sources']))

        compliant_keys.append(key)
    
    return groups, compliant_keys


def extract_manual_info(filename: str) -> dict:
    """Extract firmware family and version from filename."""
    # Pattern: u-blox-{family}-{version}_InterfaceDescription_...
    # Examples:
    #   u-blox-F9-HPG-1.51_InterfaceDescription_...
    #   u-blox-M10-SPG-5.30_InterfaceDescription_...
    #   u-blox-20-HPG-2.00_InterfaceDescription_...
    #   F9-HPS-1.21_InterfaceDescription_...
    #   M9-ADR-5.10_InterfaceDescription_...
    #   u-blox_ZED-F9H_InterfaceDescription_...

    # Pattern 1: u-blox-{family}-{type}-{version}_
    match = re.match(r'u-blox-([A-Z0-9]+-[A-Z]+-[L0-9.]+)_', filename)
    if match:
        full_id = match.group(1)
        parts = full_id.rsplit('-', 1)
        if len(parts) == 2:
            return {"family": parts[0], "version": parts[1], "full_id": full_id}

    # Pattern 2: {family}-{type}-{version}_ (no u-blox prefix)
    match = re.match(r'([A-Z0-9]+-[A-Z]+-\d+\.\d+)_', filename)
    if match:
        full_id = match.group(1)
        parts = full_id.rsplit('-', 1)
        if len(parts) == 2:
            return {"family": parts[0], "version": parts[1], "full_id": full_id}

    # Pattern 3: u-blox_ZED-{device}_  (ZED-F9H style)
    match = re.match(r'u-blox_ZED-([A-Z0-9]+)_', filename)
    if match:
        device = match.group(1)
        return {"family": f"ZED-{device}", "version": "unknown", "full_id": device}

    # Pattern 4: {family}-{type}-{version}_InterfaceDescription_... with long suffix
    match = re.match(r'([A-Z0-9]+-[A-Z]+-\d+\.\d+)_InterfaceDescription', filename)
    if match:
        full_id = match.group(1)
        parts = full_id.rsplit('-', 1)
        if len(parts) == 2:
            return {"family": parts[0], "version": parts[1], "full_id": full_id}

    # Fallback: try alternate patterns
    match = re.match(r'u-blox-([A-Z0-9-]+)-(\d+\.\d+)', filename)
    if match:
        return {"family": match.group(1), "version": match.group(2), "full_id": f"{match.group(1)}-{match.group(2)}"}
    
    return {"family": "unknown", "version": "unknown", "full_id": filename}


def merge_keys(input_dir: Path, output_file: Path):
    """Merge all extracted keys into a unified database."""
    
    # Collect all keys by key_id
    keys_by_id: dict[str, dict] = {}
    keys_by_name: dict[str, dict] = {}
    
    # Track which manuals contain each key
    key_sources: dict[str, list[dict]] = defaultdict(list)
    
    # Process each extracted file
    files = sorted(input_dir.glob("*_gemini_config_keys.json"))
    print(f"Processing {len(files)} extraction files...")
    
    for f in files:
        manual_info = extract_manual_info(f.name)
        print(f"  {manual_info['full_id']}: ", end="")
        
        with open(f) as fp:
            data = json.load(fp)
        
        file_keys = 0
        for key in data.get("keys", []):
            key_id = key.get("key_id", "")
            name = key.get("name", "")
            
            if not key_id or not name:
                continue
            
            file_keys += 1
            
            # Track source
            source_id = manual_info["full_id"]
            key_sources[key_id].append({
                "family": manual_info["family"],
                "version": manual_info["version"],
                "filename": f.name,
            })

            # Merge key data (prefer latest version by keeping last seen)
            if key_id not in keys_by_id:
                keys_by_id[key_id] = key.copy()
                keys_by_id[key_id]["sources"] = [source_id]
                # Initialize sources for each enum value
                if keys_by_id[key_id].get("inline_enum"):
                    enum_values = keys_by_id[key_id]["inline_enum"].get("values")
                    if isinstance(enum_values, dict):
                        for val in enum_values.values():
                            if isinstance(val, dict):
                                val["sources"] = [source_id]
                    elif isinstance(enum_values, list):
                        # Convert list to dict and add sources
                        new_values = {}
                        for item in enum_values:
                            if isinstance(item, dict) and 'name' in item:
                                new_values[item['name']] = {
                                    'value': item.get('value', 0),
                                    'description': item.get('description', ''),
                                    'sources': [source_id]
                                }
                        keys_by_id[key_id]["inline_enum"]["values"] = new_values
            else:
                # Merge: keep richer data (more fields, longer description)
                existing = keys_by_id[key_id]

                # Add this manual to key sources
                if source_id not in existing.get("sources", []):
                    existing.setdefault("sources", []).append(source_id)

                # Merge inline_enum values (take union of all enum values)
                if key.get("inline_enum"):
                    key_values = key["inline_enum"].get("values")

                    # Convert list to dict if needed
                    if isinstance(key_values, list):
                        key_values = {
                            item['name']: {'value': item.get('value', 0), 'description': item.get('description', '')}
                            for item in key_values if isinstance(item, dict) and 'name' in item
                        }

                    if not existing.get("inline_enum"):
                        existing["inline_enum"] = {"values": {}}
                        for enum_name, val in key_values.items():
                            val_copy = val.copy() if isinstance(val, dict) else {"value": val}
                            val_copy["sources"] = [source_id]
                            existing["inline_enum"]["values"][enum_name] = val_copy
                    else:
                        existing_values = existing["inline_enum"].get("values", {})
                        # Ensure existing_values is a dict
                        if isinstance(existing_values, list):
                            existing_values = {
                                item['name']: {'value': item.get('value', 0), 'description': item.get('description', '')}
                                for item in existing_values if isinstance(item, dict) and 'name' in item
                            }
                            existing["inline_enum"]["values"] = existing_values

                        if isinstance(key_values, dict):
                            # Get existing numeric values to avoid duplicates
                            existing_numeric = {v.get("value") for v in existing_values.values() if isinstance(v, dict)}
                            for enum_name, val in key_values.items():
                                if enum_name not in existing_values:
                                    # Only add if numeric value doesn't already exist
                                    if isinstance(val, dict) and val.get("value") not in existing_numeric:
                                        val_copy = val.copy()
                                        val_copy["sources"] = [source_id]
                                        existing_values[enum_name] = val_copy
                                else:
                                    # Enum value exists - add source if not already tracked
                                    existing_val = existing_values[enum_name]
                                    if isinstance(existing_val, dict):
                                        if source_id not in existing_val.get("sources", []):
                                            existing_val.setdefault("sources", []).append(source_id)
                
                # Prefer entry with bitfield if other doesn't have it
                if key.get("bitfield") and not existing.get("bitfield"):
                    existing["bitfield"] = key["bitfield"]
                
                # Prefer longer description
                if len(key.get("description", "")) > len(existing.get("description", "")):
                    existing["description"] = key["description"]
            
            # Also index by name for cross-reference
            keys_by_name[name] = keys_by_id[key_id]
        
        print(f"{file_keys} keys")
    
    # Build output structure
    unique_keys = list(keys_by_id.values())
    
    # Make keys schema-compliant (adds group, item_id, fixes scale format, etc.)
    print("\nApplying schema compliance transformations...")
    groups, compliant_keys = make_schema_compliant(unique_keys)
    
    # Build output
    output = {
        "schema_version": "1.0",
        "source_documents": [],  # Can be populated with manual metadata
        "groups": groups,
        "keys": sorted(compliant_keys, key=lambda k: k.get("name", "")),
    }
    
    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as fp:
        json.dump(output, fp, indent=2)
    
    print(f"\nMerge complete:")
    print(f"  Unique keys: {len(compliant_keys)}")
    print(f"  Groups: {len(groups)}")
    print(f"  Output: {output_file}")
    
    # Summary stats
    keys_with_enum = sum(1 for k in compliant_keys if k.get("inline_enum"))
    keys_with_bitfield = sum(1 for k in compliant_keys if k.get("bitfield"))
    keys_with_scale = sum(1 for k in compliant_keys if k.get("scale"))
    keys_with_unit = sum(1 for k in compliant_keys if k.get("unit"))
    print(f"\n  Keys with enums: {keys_with_enum}")
    print(f"  Keys with bitfields: {keys_with_bitfield}")
    print(f"  Keys with scale: {keys_with_scale}")
    print(f"  Keys with unit: {keys_with_unit}")
    
    # Validate against schema if available
    try:
        from jsonschema import Draft202012Validator
        schema_file = Path("schema/ubx-config-keys-schema.json")
        if schema_file.exists():
            with open(schema_file) as f:
                schema = json.load(f)
            validator = Draft202012Validator(schema)
            errors = list(validator.iter_errors(output))
            if errors:
                print(f"\n  ⚠ Schema validation: {len(errors)} errors")
            else:
                print(f"\n  ✓ Schema validation: PASSED")
    except ImportError:
        print(f"\n  (jsonschema not installed - skipping validation)")


def main():
    parser = argparse.ArgumentParser(description="Merge config keys from multiple extractions")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/config_keys/by-manual"),
        help="Directory containing extracted JSON files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/config_keys/unified_config_keys.json"),
        help="Output file for merged database",
    )
    args = parser.parse_args()
    
    merge_keys(args.input_dir, args.output)


if __name__ == "__main__":
    main()
