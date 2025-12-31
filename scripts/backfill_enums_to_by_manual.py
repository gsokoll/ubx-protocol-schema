#!/usr/bin/env python3
"""Backfill enumeration structures into by-manual JSONs using enumerations.json.

The by-manual extractions have enum values embedded in description strings.
This script adds proper `enumeration` objects to fields that match known enums.

Usage:
    python scripts/backfill_enums_to_by_manual.py --dry-run  # Preview changes
    python scripts/backfill_enums_to_by_manual.py            # Apply changes
"""

import argparse
import json
import os
from pathlib import Path


def load_enumerations(enums_path: Path) -> dict:
    """Load the enumerations.json file."""
    with open(enums_path) as f:
        return json.load(f)


def find_matching_enum(field_name: str, msg_name: str, enumerations: dict) -> str | None:
    """Find an enumeration that matches the field name."""
    # Direct match
    if field_name in enumerations:
        return field_name
    
    # Context-specific field name mappings (by-manual name -> enumerations.json name)
    # Some fields were renamed to avoid confusion with reserved words
    # Format: (field_name, msg_pattern) -> enum_name
    context_mappings = {
        ('type', 'MGA-ACK'): 'ackType',  # Only MGA-ACK.type is ackType
    }
    
    for (field, msg_pattern), enum_name in context_mappings.items():
        if field_name == field and msg_pattern in msg_name:
            if enum_name in enumerations:
                return enum_name
    
    return None


def backfill_file(file_path: Path, enumerations: dict, dry_run: bool) -> dict:
    """Backfill enumerations into a single by-manual JSON file.
    
    Returns:
        Dict with backfill results
    """
    with open(file_path) as f:
        data = json.load(f)
    
    changes = []
    modified = False
    
    for msg in data.get('messages', []):
        msg_name = msg.get('name', '')
        payload = msg.get('payload', {})
        
        for field in payload.get('fields', []):
            field_name = field.get('name', '')
            
            # Skip if already has enumeration
            if 'enumeration' in field:
                continue
            
            # Check if this field matches a known enum
            enum_name = find_matching_enum(field_name, msg_name, enumerations)
            if not enum_name:
                continue
            
            enum_def = enumerations[enum_name]
            
            # Add enumeration to field
            changes.append({
                'message': msg_name,
                'field': field_name,
                'enum': enum_name,
                'values_count': len(enum_def.get('values', [])),
            })
            
            if not dry_run:
                field['enumeration'] = {
                    'values': enum_def.get('values', []).copy()
                }
                modified = True
    
    if modified and not dry_run:
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    return {
        'file': file_path.name,
        'changes': changes,
        'modified': modified,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Backfill enumeration structures into by-manual JSONs"
    )
    parser.add_argument(
        "--enums-file",
        type=Path,
        default=Path("data/ubx/validated/enumerations.json"),
        help="Path to enumerations.json",
    )
    parser.add_argument(
        "--by-manual-dir",
        type=Path,
        default=Path("data/ubx/by-manual"),
        help="Directory containing *_anthropic.json files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying files",
    )
    
    args = parser.parse_args()
    
    print(f"Loading enumerations from: {args.enums_file}")
    enumerations = load_enumerations(args.enums_file)
    print(f"Found {len(enumerations)} enumeration definitions")
    
    # Process all by-manual files
    results = []
    for f in sorted(os.listdir(args.by_manual_dir)):
        if not f.endswith('_anthropic.json'):
            continue
        
        file_path = args.by_manual_dir / f
        result = backfill_file(file_path, enumerations, args.dry_run)
        
        if result['changes']:
            results.append(result)
    
    # Print summary
    if args.dry_run:
        print(f"\n{'='*60}")
        print("DRY RUN - No files modified")
        print(f"{'='*60}")
    
    total_changes = 0
    print(f"\nFound {len(results)} files with fields to backfill:\n")
    
    for result in results:
        print(f"  {result['file']}:")
        for change in result['changes']:
            print(f"    - {change['message']}.{change['field']} <- {change['enum']} ({change['values_count']} values)")
            total_changes += 1
    
    print(f"\nTotal: {total_changes} fields across {len(results)} files")
    
    if not args.dry_run and results:
        print(f"\n✓ Updated {len(results)} by-manual files")
    elif not results:
        print("\n✓ No backfill needed")


if __name__ == "__main__":
    main()
