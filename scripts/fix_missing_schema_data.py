#!/usr/bin/env python3
"""Fix validated message JSONs by merging missing bitfield bits and enum values.

This script addresses the issue where the consensus validation picked one source's
definitions rather than taking the union of all values across sources.

Usage:
    python scripts/fix_missing_schema_data.py --dry-run  # Preview changes
    python scripts/fix_missing_schema_data.py            # Apply fixes
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any


def load_all_data_from_manuals(by_manual_dir: Path) -> tuple[dict, dict]:
    """Load all bitfield and enumeration definitions from by-manual extractions.
    
    Returns:
        Tuple of:
        - Dict mapping (message_name, field_name) -> {bit_name: bit_def}
        - Dict mapping (message_name, field_name) -> {value: enum_def}
    """
    all_bitfields = {}
    all_enums = {}
    
    for f in os.listdir(by_manual_dir):
        if not f.endswith('_anthropic.json'):
            continue
        
        source = f.replace('_anthropic.json', '')
        path = by_manual_dir / f
        
        with open(path) as fp:
            data = json.load(fp)
        
        for msg in data.get('messages', []):
            msg_name = msg.get('name', '').replace('UBX-', '')
            payload = msg.get('payload', {})
            
            for field in payload.get('fields', []):
                field_name = field['name']
                key = (msg_name, field_name)
                
                # Collect bitfields
                if 'bitfield' in field:
                    if key not in all_bitfields:
                        all_bitfields[key] = {}
                    
                    for bit in field['bitfield'].get('bits', []):
                        bit_name = bit.get('name', '')
                        if not bit_name:
                            continue
                        
                        # Skip reserved bits
                        if bit.get('reserved', False) or 'reserved' in bit_name.lower():
                            continue
                        
                        if bit_name not in all_bitfields[key]:
                            all_bitfields[key][bit_name] = bit.copy()
                            all_bitfields[key][bit_name]['_sources'] = [source]
                        else:
                            all_bitfields[key][bit_name]['_sources'].append(source)
                
                # Collect enumerations
                if 'enumeration' in field:
                    if key not in all_enums:
                        all_enums[key] = {}
                    
                    for val in field['enumeration'].get('values', []):
                        numeric_val = val.get('value')
                        if numeric_val is None:
                            continue
                        
                        if numeric_val not in all_enums[key]:
                            all_enums[key][numeric_val] = val.copy()
                            all_enums[key][numeric_val]['_sources'] = [source]
                        else:
                            all_enums[key][numeric_val]['_sources'].append(source)
    
    return all_bitfields, all_enums


def find_missing_bits(validated_field: dict, all_bits: dict) -> list:
    """Find bits that exist in by-manual but not in validated schema."""
    validated_bit_names = set()
    
    if 'bitfield' in validated_field:
        for bit in validated_field['bitfield'].get('bits', []):
            validated_bit_names.add(bit.get('name', ''))
    
    missing = []
    for bit_name, bit_def in all_bits.items():
        if bit_name not in validated_bit_names:
            clean_bit = {k: v for k, v in bit_def.items() if not k.startswith('_')}
            missing.append(clean_bit)
    
    return missing


def find_missing_enum_values(validated_field: dict, all_values: dict) -> list:
    """Find enum values that exist in by-manual but not in validated schema."""
    validated_values = set()
    
    if 'enumeration' in validated_field:
        for val in validated_field['enumeration'].get('values', []):
            validated_values.add(val.get('value'))
    
    missing = []
    for numeric_val, val_def in all_values.items():
        if numeric_val not in validated_values:
            clean_val = {k: v for k, v in val_def.items() if not k.startswith('_')}
            missing.append(clean_val)
    
    return missing


def fix_validated_message(validated_path: Path, all_bitfields: dict, all_enums: dict, dry_run: bool) -> dict:
    """Fix a single validated message JSON by adding missing bits and enum values.
    
    Returns:
        Dict with fix details
    """
    with open(validated_path) as f:
        data = json.load(f)
    
    msg_name = data.get('name', '').replace('UBX-', '')
    bitfield_fixes = []
    enum_fixes = []
    modified = False
    
    for field in data.get('fields', []):
        field_name = field['name']
        key = (msg_name, field_name)
        
        # Fix bitfields
        if key in all_bitfields and 'bitfield' in field:
            missing_bits = find_missing_bits(field, all_bitfields[key])
            
            if missing_bits:
                missing_bits.sort(key=lambda b: b.get('bit_start', 999))
                
                bitfield_fixes.append({
                    'field': field_name,
                    'missing': [b.get('name') for b in missing_bits],
                    'positions': [(b.get('bit_start'), b.get('bit_end')) for b in missing_bits],
                })
                
                if not dry_run:
                    existing_bits = field['bitfield'].get('bits', [])
                    existing_bits.extend(missing_bits)
                    existing_bits.sort(key=lambda b: b.get('bit_start', 0))
                    field['bitfield']['bits'] = existing_bits
                    modified = True
        
        # Fix enumerations
        if key in all_enums and 'enumeration' in field:
            missing_values = find_missing_enum_values(field, all_enums[key])
            
            if missing_values:
                missing_values.sort(key=lambda v: v.get('value', 999))
                
                enum_fixes.append({
                    'field': field_name,
                    'missing': [f"{v.get('name')}={v.get('value')}" for v in missing_values],
                })
                
                if not dry_run:
                    existing_values = field['enumeration'].get('values', [])
                    existing_values.extend(missing_values)
                    existing_values.sort(key=lambda v: v.get('value', 0))
                    field['enumeration']['values'] = existing_values
                    modified = True
    
    if modified and not dry_run:
        with open(validated_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    return {
        'message': msg_name,
        'file': validated_path.name,
        'bitfield_fixes': bitfield_fixes,
        'enum_fixes': enum_fixes,
        'modified': modified,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Fix validated JSONs by merging missing bitfield bits and enum values"
    )
    parser.add_argument(
        "--by-manual-dir",
        type=Path,
        default=Path("data/ubx/by-manual"),
        help="Directory containing *_anthropic.json extraction files",
    )
    parser.add_argument(
        "--validated-dir",
        type=Path,
        default=Path("data/ubx/validated/messages"),
        help="Directory containing validated message JSON files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying files",
    )
    parser.add_argument(
        "--message",
        type=str,
        help="Fix only a specific message (e.g., NAV-PVT, CFG-NAV5)",
    )
    
    args = parser.parse_args()
    
    print(f"Loading data from: {args.by_manual_dir}")
    all_bitfields, all_enums = load_all_data_from_manuals(args.by_manual_dir)
    print(f"Found {len(all_bitfields)} bitfield combinations, {len(all_enums)} enum combinations")
    
    # Process validated messages
    results = []
    for f in sorted(os.listdir(args.validated_dir)):
        if not f.endswith('.json'):
            continue
        
        if args.message and args.message not in f:
            continue
        
        validated_path = args.validated_dir / f
        result = fix_validated_message(validated_path, all_bitfields, all_enums, args.dry_run)
        
        if result['bitfield_fixes'] or result['enum_fixes']:
            results.append(result)
    
    # Print summary
    if args.dry_run:
        print(f"\n{'='*60}")
        print("DRY RUN - No files modified")
        print(f"{'='*60}")
    
    total_bits = 0
    total_enums = 0
    
    print(f"\nFound {len(results)} messages with missing data:\n")
    
    for result in results:
        has_output = False
        
        if result['bitfield_fixes']:
            if not has_output:
                print(f"  {result['message']} ({result['file']}):")
                has_output = True
            for fix in result['bitfield_fixes']:
                names = ', '.join(fix['missing'])
                print(f"    [bitfield] {fix['field']}: +{len(fix['missing'])} ({names})")
                total_bits += len(fix['missing'])
        
        if result['enum_fixes']:
            if not has_output:
                print(f"  {result['message']} ({result['file']}):")
                has_output = True
            for fix in result['enum_fixes']:
                names = ', '.join(fix['missing'])
                print(f"    [enum] {fix['field']}: +{len(fix['missing'])} ({names})")
                total_enums += len(fix['missing'])
    
    print(f"\nTotal: {total_bits} missing bits, {total_enums} missing enum values across {len(results)} messages")
    
    if not args.dry_run and results:
        print(f"\n✓ Fixed {len(results)} validated message files")
    elif not results:
        print("\n✓ No fixes needed - all validated messages are complete")


if __name__ == "__main__":
    main()
