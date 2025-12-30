"""Bitfield merging for UBX message validation.

When multiple extraction sources agree on a message structure (same fingerprint),
their bitfield definitions may still differ. This module merges bitfield bits
to create a superset containing all documented bits.
"""

from typing import Any


def merge_bitfield_bits(bits_lists: list[list[dict]]) -> list[dict]:
    """Merge multiple lists of bitfield bits into a superset.
    
    Args:
        bits_lists: List of bit definition lists from different sources
        
    Returns:
        Merged list of bits containing all unique bits, sorted by bit_start
    """
    # Collect all bits by name, keeping the most complete definition
    merged = {}  # bit_name -> bit definition
    
    for bits in bits_lists:
        for bit in bits:
            name = bit.get('name', '')
            if not name:
                continue
            
            # Skip reserved bits
            if bit.get('reserved', False) or 'reserved' in name.lower():
                continue
            
            if name not in merged:
                merged[name] = bit.copy()
            else:
                # Keep the one with more complete description
                existing = merged[name]
                if len(bit.get('description', '')) > len(existing.get('description', '')):
                    merged[name] = bit.copy()
    
    # Sort by bit_start position
    result = sorted(merged.values(), key=lambda b: b.get('bit_start', 0))
    return result


def merge_field_bitfields(winning_field: dict, all_fields: list[dict]) -> dict:
    """Merge bitfield from multiple source fields into winning field.
    
    Args:
        winning_field: The field definition from the winning source
        all_fields: List of the same field from all agreeing sources
        
    Returns:
        Updated field with merged bitfield bits
    """
    if 'bitfield' not in winning_field:
        return winning_field
    
    # Collect all bit definitions
    bits_lists = []
    for field in all_fields:
        if 'bitfield' in field:
            bits = field['bitfield'].get('bits', [])
            if bits:
                bits_lists.append(bits)
    
    if not bits_lists:
        return winning_field
    
    # Merge bits
    merged_bits = merge_bitfield_bits(bits_lists)
    
    # Update winning field
    result = winning_field.copy()
    result['bitfield'] = result.get('bitfield', {}).copy()
    result['bitfield']['bits'] = merged_bits
    
    return result


def merge_message_bitfields(winning_message: dict, all_messages: list[dict]) -> dict:
    """Merge all bitfields in a message from multiple sources.
    
    Args:
        winning_message: The message definition from the winning source
        all_messages: List of the same message from all agreeing sources
        
    Returns:
        Updated message with all bitfields merged
    """
    # Get fields from winning message
    winning_fields = winning_message.get('fields', [])
    if not winning_fields:
        payload = winning_message.get('payload', {})
        winning_fields = payload.get('fields', [])
    
    if not winning_fields:
        return winning_message
    
    # Build lookup of fields by (name, byte_offset)
    def get_field_key(field):
        return (field.get('name', ''), field.get('byte_offset', 0))
    
    # Collect fields from all sources
    all_source_fields = {}  # field_key -> list of field dicts
    for msg in all_messages:
        fields = msg.get('fields', [])
        if not fields:
            payload = msg.get('payload', {})
            fields = payload.get('fields', [])
        
        for field in fields:
            key = get_field_key(field)
            if key not in all_source_fields:
                all_source_fields[key] = []
            all_source_fields[key].append(field)
    
    # Merge bitfields for each field
    merged_fields = []
    for field in winning_fields:
        key = get_field_key(field)
        if key in all_source_fields and 'bitfield' in field:
            merged_field = merge_field_bitfields(field, all_source_fields[key])
            merged_fields.append(merged_field)
        else:
            merged_fields.append(field)
    
    # Update winning message
    result = winning_message.copy()
    if 'fields' in result:
        result['fields'] = merged_fields
    elif 'payload' in result:
        result['payload'] = result['payload'].copy()
        result['payload']['fields'] = merged_fields
    
    return result
