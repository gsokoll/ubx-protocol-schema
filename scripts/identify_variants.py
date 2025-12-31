"""Identify variant message types in extraction data.

Variant messages are those with subtypes (e.g., MGA-INI-POS_XYZ, MGA-INI-TIME_UTC)
that should be kept separate rather than merged.
"""

import json
from pathlib import Path
from collections import defaultdict

def main():
    extractions_dir = Path('data/ubx/by-manual')
    
    # Collect all message names across all extractions
    all_messages = defaultdict(list)  # base_name -> [full_names]
    
    for f in sorted(extractions_dir.glob('*_anthropic.json')):
        data = json.load(open(f))
        source = f.stem[:40]
        
        for msg in data.get('messages', []):
            name = msg.get('name', '')
            if name:
                all_messages[name].append(source)
    
    print(f"Total unique message names: {len(all_messages)}")
    print()
    
    # Find messages that look like variants (contain hyphen after class-msg pattern)
    # Pattern: UBX-CLASS-MSG-SUBTYPE or UBX-CLASS-MSG_SUBTYPE
    variant_bases = defaultdict(list)
    
    for name in all_messages:
        # Skip if not UBX format
        if not name.startswith('UBX-'):
            continue
        
        parts = name[4:].split('-')  # Remove UBX- prefix
        if len(parts) >= 2:
            base = f"UBX-{parts[0]}-{parts[1].split('_')[0]}"  # e.g., UBX-MGA-INI
            if name != base:
                variant_bases[base].append(name)
    
    print("=" * 60)
    print("VARIANT MESSAGE FAMILIES")
    print("=" * 60)
    
    for base, variants in sorted(variant_bases.items()):
        if len(variants) > 0:
            print(f"\n{base}:")
            # Check if base also exists
            if base in all_messages:
                print(f"  [BASE EXISTS] {base}")
            for v in sorted(variants):
                sources = len(all_messages[v])
                print(f"  - {v} (in {sources} extractions)")
    
    # Find messages with overlaps that might be variants
    print()
    print("=" * 60)
    print("MESSAGES WITH FIELD OVERLAPS (potential undetected variants)")
    print("=" * 60)
    
    # Load canonical issues
    issues = json.load(open('analysis_reports/canonical_issues.json'))
    overlap_files = set()
    for issue in issues['issues']:
        if issue['issue'] == 'overlapping_fields':
            overlap_files.add(issue['file'].replace('.json', ''))
    
    # Cross-reference with variant bases
    for f in sorted(overlap_files):
        msg_name = f"UBX-{f}"
        is_variant_base = msg_name in variant_bases
        has_subtypes = len(variant_bases.get(msg_name, [])) > 0
        
        if is_variant_base or has_subtypes:
            print(f"  {f}: HAS SUBTYPES - {variant_bases.get(msg_name, [])}")
        else:
            print(f"  {f}: NO SUBTYPES DETECTED")
    
    # Summary of what needs splitting
    print()
    print("=" * 60)
    print("RECOMMENDED ACTIONS")
    print("=" * 60)
    
    # Messages where base exists AND subtypes exist (should not merge)
    print("\n1. DO NOT MERGE (base + subtypes both exist):")
    for base, variants in sorted(variant_bases.items()):
        if base in all_messages and len(variants) > 0:
            print(f"   {base} -> keep separate from {variants}")
    
    # Messages with overlaps but no detected subtypes (need investigation)
    print("\n2. INVESTIGATE (overlaps but no subtypes in extraction):")
    for f in sorted(overlap_files):
        msg_name = f"UBX-{f}"
        if msg_name not in variant_bases or len(variant_bases.get(msg_name, [])) == 0:
            if msg_name not in all_messages:
                continue
            print(f"   {f}")


if __name__ == '__main__':
    main()
