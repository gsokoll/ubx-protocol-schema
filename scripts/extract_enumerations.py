#!/usr/bin/env python3
"""Extract structured enumeration values from field descriptions.

Parses enum-like patterns in field descriptions (e.g., "0 = no fix, 1 = 2D-fix")
and generates structured enumeration data.

Usage:
    python scripts/extract_enumerations.py --report
    python scripts/extract_enumerations.py --apply
    python scripts/extract_enumerations.py --output data/enumerations.json
"""

import argparse
import json
import re
from pathlib import Path
from collections import defaultdict
from typing import Optional


def normalize_enum_name(description: str, max_length: int = 30) -> str:
    """Convert enum value description to snake_case name.
    
    Examples:
        "no fix" -> "no_fix"
        "2D-fix" -> "fix_2d"
        "3D-fix" -> "fix_3d"
        "GNSS + dead reckoning combined" -> "gnss_dr"
        "Dead Reckoning only" -> "dead_reckoning"
        "airborne with <1g acceleration" -> "airborne_1g"
    """
    name = description.strip()
    
    # Remove parenthetical notes and version info
    name = re.sub(r'\([^)]*\)', '', name)  # Remove (...)
    name = re.sub(r'not supported.*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'extra values.*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'for protocol.*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'as defined by.*', '', name, flags=re.IGNORECASE)
    
    # Simplify common verbose patterns
    replacements = [
        (r'dead reckoning', 'dr'),
        (r'combined', ''),
        (r'acceleration', ''),
        (r'airborne with', 'airborne'),
        (r'wrist[- ]worn watch', 'wrist'),
        (r'user[- ]defined', 'user'),
        (r'is not overridden', 'default'),
        (r'set main talker id to', ''),
        (r'use gnss[- ]specific talker id', 'gnss_specific'),
        (r'use the main talker id', 'use_main'),
        (r'satellites are not output', 'no_output'),
        (r'use proprietary numbering', 'proprietary'),
        (r'nmea version', 'v'),
        (r'enable pio.*output', 'pio_enabled'),
        (r'low means inside', 'inside'),
        (r'low means outside.*', 'outside'),
    ]
    for pattern, replacement in replacements:
        name = re.sub(pattern, replacement, name, flags=re.IGNORECASE)
    
    # Handle special patterns
    name = re.sub(r'^(\d)D[-\s]?', r'_\1d_', name)  # "2D-fix" -> "_2d_fix"
    name = re.sub(r'<(\d)g', r'\1g', name)  # "<1g" -> "1g"
    name = re.sub(r'\s*\+\s*', '_', name)  # "GNSS + DR" -> "GNSS_DR"
    
    # Convert to lowercase and replace separators
    name = name.lower()
    name = re.sub(r'[-\s]+', '_', name)  # spaces/hyphens to underscores
    name = re.sub(r'[^a-z0-9_]', '', name)  # remove special chars
    name = re.sub(r'_+', '_', name)  # collapse multiple underscores
    name = name.strip('_')
    
    # Handle leading numbers
    if name and name[0].isdigit():
        name = '_' + name
    
    # Truncate if still too long, preserving word boundaries
    if len(name) > max_length:
        parts = name.split('_')
        truncated = []
        length = 0
        for part in parts:
            if length + len(part) + 1 <= max_length:
                truncated.append(part)
                length += len(part) + 1
            else:
                break
        name = '_'.join(truncated) if truncated else name[:max_length]
    
    return name or 'unknown'


def parse_enum_values(description: str) -> Optional[list[dict]]:
    """Extract enumeration values from a description string.
    
    Handles patterns like:
        - "0 = no fix, 1 = 2D-fix, 2 = 3D-fix"
        - "0x01 = Dead Reckoning, 0x02 = 2D-Fix"
        - "• 0 = GPS • 1 = SBAS • 2 = Galileo"
    
    Returns list of {"value": int, "name": str, "description": str} or None if no enums found.
    """
    values = []
    seen_nums = set()
    
    # Handle hex values: "0x21 = description"
    hex_pattern = r'0x([0-9a-fA-F]+)\s*=\s*([^,•\n]+?)(?:,|•|\n|$)'
    for match in re.finditer(hex_pattern, description):
        num_str = match.group(1)
        desc = match.group(2).strip()
        num = int(num_str, 16)
        
        if num in seen_nums:
            continue
        seen_nums.add(num)
        
        desc = desc.strip(' ,.')
        if not desc:
            continue
            
        values.append({
            "value": num,
            "name": normalize_enum_name(desc),
            "description": desc
        })
    
    # Handle decimal values: "0 = description"
    # Use negative lookbehind to avoid matching "0x21" as "21"
    decimal_pattern = r'(?<!x)(?<![0-9a-fA-F])(\d+)\s*=\s*([^,•\n\d][^,•\n]*?)(?:,|•|\n|$)'
    for match in re.finditer(decimal_pattern, description):
        num_str = match.group(1)
        desc = match.group(2).strip()
        num = int(num_str)
        
        if num in seen_nums:
            continue
        seen_nums.add(num)
        
        desc = desc.strip(' ,.')
        if not desc:
            continue
            
        values.append({
            "value": num,
            "name": normalize_enum_name(desc),
            "description": desc
        })
    
    # Only return if we found at least 2 enum values
    if len(values) >= 2:
        # Sort by value
        values.sort(key=lambda x: x["value"])
        return values
    
    return None


def extract_enums_from_message(msg_path: Path) -> list[dict]:
    """Extract all enum fields from a message JSON file."""
    with open(msg_path) as f:
        msg = json.load(f)
    
    results = []
    for field in msg.get("fields", []):
        desc = field.get("description", "")
        enum_values = parse_enum_values(desc)
        
        if enum_values:
            results.append({
                "message": msg["name"],
                "field_name": field["name"],
                "data_type": field.get("data_type", "U1"),
                "byte_offset": field.get("byte_offset"),
                "original_description": desc,
                "enumeration": {
                    "values": enum_values,
                    "reserved_handling": "allow"
                }
            })
    
    return results


def extract_all_enums(messages_dir: Path) -> list[dict]:
    """Extract enums from all message files."""
    all_enums = []
    
    for msg_file in sorted(messages_dir.glob("*.json")):
        enums = extract_enums_from_message(msg_file)
        all_enums.extend(enums)
    
    return all_enums


def build_canonical_enums(all_enums: list[dict]) -> dict:
    """Build canonical enum definitions from extracted data.
    
    Groups by field name and merges values from multiple messages.
    """
    by_field = defaultdict(list)
    
    for enum in all_enums:
        by_field[enum["field_name"]].append(enum)
    
    canonical = {}
    for field_name, instances in by_field.items():
        # Use the most complete set of values
        best = max(instances, key=lambda x: len(x["enumeration"]["values"]))
        
        canonical[field_name] = {
            "type": best["data_type"],
            "values": best["enumeration"]["values"],
            "occurrences": len(instances),
            "messages": [e["message"] for e in instances]
        }
    
    return canonical


def apply_enumerations_to_messages(messages_dir: Path, enums_file: Path) -> int:
    """Apply enumeration data from canonical file to message JSON files.
    
    Returns count of fields updated.
    """
    # Load canonical enumerations
    with open(enums_file) as f:
        canonical = json.load(f)
    
    updated_count = 0
    
    for msg_file in sorted(messages_dir.glob("*.json")):
        with open(msg_file) as f:
            msg = json.load(f)
        
        modified = False
        for field in msg.get("fields", []):
            field_name = field.get("name")
            
            # Check if this field has a canonical enumeration
            if field_name in canonical:
                enum_data = canonical[field_name]
                
                # Add enumeration to field (only values, not metadata)
                field["enumeration"] = {
                    "values": enum_data["values"]
                }
                modified = True
                updated_count += 1
        
        if modified:
            with open(msg_file, "w") as f:
                json.dump(msg, f, indent=2)
            print(f"  Updated: {msg_file.name}")
    
    return updated_count


def print_report(all_enums: list[dict], canonical: dict):
    """Print extraction report."""
    print("=" * 60)
    print("ENUMERATION EXTRACTION REPORT")
    print("=" * 60)
    print(f"\nTotal enum fields found: {len(all_enums)}")
    print(f"Unique enum field names: {len(canonical)}")
    print()
    
    print("CANONICAL ENUMERATIONS:")
    print("-" * 40)
    for field_name, data in sorted(canonical.items(), key=lambda x: -x[1]["occurrences"]):
        print(f"\n{field_name} ({data['type']}) - {data['occurrences']} occurrence(s)")
        print(f"  Messages: {', '.join(data['messages'][:3])}{'...' if len(data['messages']) > 3 else ''}")
        print("  Values:")
        for v in data["values"]:
            print(f"    {v['value']:3d} = {v['name']:<25} ({v['description']})")
    
    print("\n" + "=" * 60)
    print("DETAILED EXTRACTION LOG:")
    print("=" * 60)
    for enum in all_enums:
        print(f"\n{enum['message']}.{enum['field_name']} (offset {enum['byte_offset']}, {enum['data_type']})")
        print(f"  Original: {enum['original_description'][:80]}...")
        print(f"  Parsed values: {len(enum['enumeration']['values'])}")
        for v in enum['enumeration']['values']:
            print(f"    {v['value']:3d} = {v['name']}")


def main():
    parser = argparse.ArgumentParser(description="Extract enumeration values from field descriptions")
    parser.add_argument("--messages-dir", type=Path, default=Path("data/validated/messages"),
                        help="Directory containing validated message JSON files")
    parser.add_argument("--report", action="store_true",
                        help="Print extraction report without modifying files")
    parser.add_argument("--output", type=Path,
                        help="Output canonical enumerations to JSON file")
    parser.add_argument("--apply", action="store_true",
                        help="Apply enumeration fields to message JSON files")
    parser.add_argument("--enums-file", type=Path, default=Path("data/enumerations.json"),
                        help="Canonical enumerations file (for --apply)")
    args = parser.parse_args()
    
    if not args.messages_dir.exists():
        print(f"Error: Messages directory not found: {args.messages_dir}")
        return 1
    
    # Extract all enums
    all_enums = extract_all_enums(args.messages_dir)
    canonical = build_canonical_enums(all_enums)
    
    if args.report or (not args.output and not args.apply):
        print_report(all_enums, canonical)
    
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(canonical, f, indent=2)
        print(f"\nWrote canonical enumerations to: {args.output}")
    
    if args.apply:
        if not args.enums_file.exists():
            print(f"Error: Enumerations file not found: {args.enums_file}")
            print("Run with --output first to generate the canonical enumerations file.")
            return 1
        
        print(f"\nApplying enumerations from {args.enums_file} to message files...")
        count = apply_enumerations_to_messages(args.messages_dir, args.enums_file)
        print(f"\nUpdated {count} field(s) with enumeration data.")
    
    return 0


if __name__ == "__main__":
    exit(main())
