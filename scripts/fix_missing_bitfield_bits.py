#!/usr/bin/env python3
"""Fix validated message JSONs by merging missing bitfield bits from by-manual extractions.

This script addresses the issue where the consensus validation picked one source's
bitfield definition rather than taking the union of all bits across sources.

Usage:
    python scripts/fix_missing_bitfield_bits.py --dry-run  # Preview changes
    python scripts/fix_missing_bitfield_bits.py            # Apply fixes
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any


def load_all_bitfields_from_manuals(by_manual_dir: Path) -> dict:
    """Load all bitfield definitions from by-manual extractions.
    
    Returns:
        Dict mapping (message_name, field_name) -> list of bit definitions
        Each bit definition includes the source manual it came from.
    """
    all_bitfields = {}  # (msg_name, field_name) -> {bit_name: bit_def}
    
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
                if 'bitfield' not in field:
                    continue
                
                field_name = field['name']
                key = (msg_name, field_name)
                
                if key not in all_bitfields:
                    all_bitfields[key] = {}
                
                for bit in field['bitfield'].get('bits', []):
                    bit_name = bit.get('name', '')
                    if not bit_name:
                        continue
                    
                    # Skip reserved bits - they're not useful for codegen
                    if bit.get('reserved', False) or 'reserved' in bit_name.lower():
                        continue
                    
                    # Keep the bit with most complete definition
                    if bit_name not in all_bitfields[key]:
                        all_bitfields[key][bit_name] = bit.copy()
                        all_bitfields[key][bit_name]['_sources'] = [source]
                    else:
                        all_bitfields[key][bit_name]['_sources'].append(source)
    
    return all_bitfields


def find_missing_bits(validated_field: dict, all_bits: dict) -> list:
    """Find bits that exist in by-manual but not in validated schema."""
    validated_bit_names = set()
    
    if 'bitfield' in validated_field:
        for bit in validated_field['bitfield'].get('bits', []):
            validated_bit_names.add(bit.get('name', ''))
    
    missing = []
    for bit_name, bit_def in all_bits.items():
        if bit_name not in validated_bit_names:
            # Remove internal tracking field
            clean_bit = {k: v for k, v in bit_def.items() if not k.startswith('_')}
            missing.append(clean_bit)
    
    return missing


def fix_validated_message(validated_path: Path, all_bitfields: dict, dry_run: bool) -> dict:
    """Fix a single validated message JSON by adding missing bits.
    
    Returns:
        Dict with fix details: message_name, fixes_applied, fields_fixed
    """
    with open(validated_path) as f:
        data = json.load(f)
    
    msg_name = data.get('name', '').replace('UBX-', '')
    fixes = []
    modified = False
    
    for field in data.get('fields', []):
        if 'bitfield' not in field:
            continue
        
        field_name = field['name']
        key = (msg_name, field_name)
        
        if key not in all_bitfields:
            continue
        
        missing_bits = find_missing_bits(field, all_bitfields[key])
        
        if missing_bits:
            # Sort by bit_start position
            missing_bits.sort(key=lambda b: b.get('bit_start', 999))
            
            fixes.append({
                'field': field_name,
                'missing_bits': [b.get('name') for b in missing_bits],
                'bit_positions': [(b.get('bit_start'), b.get('bit_end')) for b in missing_bits],
            })
            
            if not dry_run:
                # Add missing bits to the field's bitfield
                existing_bits = field['bitfield'].get('bits', [])
                existing_bits.extend(missing_bits)
                # Sort all bits by bit_start
                existing_bits.sort(key=lambda b: b.get('bit_start', 0))
                field['bitfield']['bits'] = existing_bits
                modified = True
    
    if modified and not dry_run:
        with open(validated_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    return {
        'message': msg_name,
        'file': validated_path.name,
        'fixes': fixes,
        'modified': modified,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Fix validated JSONs by merging missing bitfield bits"
    )
    parser.add_argument(
        "--by-manual-dir",
        type=Path,
        default=Path("data/by-manual"),
        help="Directory containing *_anthropic.json extraction files",
    )
    parser.add_argument(
        "--validated-dir",
        type=Path,
        default=Path("data/validated/messages"),
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
        help="Fix only a specific message (e.g., NAV-PVT)",
    )
    
    args = parser.parse_args()
    
    print(f"Loading bitfield definitions from: {args.by_manual_dir}")
    all_bitfields = load_all_bitfields_from_manuals(args.by_manual_dir)
    print(f"Found {len(all_bitfields)} unique (message, field) bitfield combinations")
    
    # Process validated messages
    results = []
    for f in sorted(os.listdir(args.validated_dir)):
        if not f.endswith('.json'):
            continue
        
        if args.message and args.message not in f:
            continue
        
        validated_path = args.validated_dir / f
        result = fix_validated_message(validated_path, all_bitfields, args.dry_run)
        
        if result['fixes']:
            results.append(result)
    
    # Print summary
    if args.dry_run:
        print(f"\n{'='*60}")
        print("DRY RUN - No files modified")
        print(f"{'='*60}")
    
    print(f"\nFound {len(results)} messages with missing bitfield bits:\n")
    
    total_fixes = 0
    for result in results:
        print(f"  {result['message']} ({result['file']}):")
        for fix in result['fixes']:
            bits = ', '.join(fix['missing_bits'])
            positions = ', '.join(f"{s}-{e}" for s, e in fix['bit_positions'])
            print(f"    - {fix['field']}: +{len(fix['missing_bits'])} bits ({bits}) at positions ({positions})")
            total_fixes += len(fix['missing_bits'])
    
    print(f"\nTotal: {total_fixes} missing bits across {len(results)} messages")
    
    if not args.dry_run and results:
        print(f"\n✓ Fixed {len(results)} validated message files")
    elif not results:
        print("\n✓ No fixes needed - all validated messages have complete bitfields")


if __name__ == "__main__":
    main()
