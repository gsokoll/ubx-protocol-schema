#!/usr/bin/env python3
"""
Extract CFG-VAL configuration keys from u-blox F9+ interface description PDFs.

Config keys are in tables with columns:
- Configuration item (name like CFG-HW-ANT_CFG_VOLTCTRL)
- Key ID (hex like 0x10a3002e)
- Type (L, U1, U2, X1, E1, etc.)
- Scale
- Unit
- Description

Enum/constant tables follow with:
- Constant (name)
- Value (integer or hex)
- Description
"""

import json
import re
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

import pdfplumber


@dataclass
class ConfigKey:
    name: str
    key_id: str
    data_type: str
    group: str = ""
    scale: Optional[str] = None
    unit: Optional[str] = None
    description: Optional[str] = None
    inline_enum: Optional[dict] = None


@dataclass
class EnumConstant:
    name: str
    value: int
    description: str


def parse_key_id(key_id_str: str) -> dict:
    """Parse key ID into components."""
    try:
        key_id = int(key_id_str, 16)
        size_id = (key_id >> 24) & 0x0F
        group_id = (key_id >> 16) & 0xFF
        item_id = key_id & 0xFFFF
        return {
            'size_id': size_id,
            'group_id': f'0x{group_id:02x}',
            'item_id': f'0x{item_id:04x}',
        }
    except:
        return {}


def extract_group_from_name(name: str) -> str:
    """Extract group name from config key name (e.g., CFG-HW from CFG-HW-ANT_CFG_VOLTCTRL)."""
    parts = name.split('-')
    if len(parts) >= 2:
        return f'{parts[0]}-{parts[1]}'
    return name


def find_config_key_tables(page) -> list[list]:
    """Find tables containing config key definitions."""
    tables = page.extract_tables() or []
    config_tables = []
    
    for table in tables:
        if not table or len(table) < 2:
            continue
        
        # Check header row for config key table pattern
        header = table[0]
        if not header:
            continue
        
        header_text = ' '.join(str(c).lower() if c else '' for c in header)
        
        # Config key tables have: Configuration item, Key ID, Type
        if ('configuration' in header_text or 'key' in header_text) and ('type' in header_text or '0x' in str(table[1] if len(table) > 1 else [])):
            config_tables.append(table)
        
        # Also check if first data row has key ID pattern
        if len(table) > 1:
            first_row = ' '.join(str(c) if c else '' for c in table[1])
            if re.search(r'0x[0-9a-fA-F]{8}', first_row) and 'CFG-' in first_row:
                config_tables.append(table)
    
    return config_tables


def find_enum_tables(page) -> list[tuple[str, list]]:
    """Find enum/constant definition tables."""
    tables = page.extract_tables() or []
    enum_tables = []
    
    for table in tables:
        if not table or len(table) < 2:
            continue
        
        header = table[0]
        if not header:
            continue
        
        header_text = ' '.join(str(c).lower() if c else '' for c in header)
        
        # Enum tables have: Constant, Value, Description
        if 'constant' in header_text and 'value' in header_text:
            enum_tables.append(table)
    
    return enum_tables


def parse_config_key_row(row: list, col_map: dict) -> Optional[ConfigKey]:
    """Parse a single config key row."""
    if not row or len(row) < 3:
        return None
    
    name = str(row[col_map.get('name', 0)] or '').strip()
    key_id = str(row[col_map.get('key_id', 1)] or '').strip()
    dtype = str(row[col_map.get('type', 2)] or '').strip()
    
    # Must have CFG- prefix and valid key ID
    if not name.startswith('CFG-') or not re.match(r'^0x[0-9a-fA-F]{8}$', key_id):
        return None
    
    scale = str(row[col_map.get('scale', 3)] or '').strip() if col_map.get('scale') is not None else None
    unit = str(row[col_map.get('unit', 4)] or '').strip() if col_map.get('unit') is not None else None
    desc = str(row[col_map.get('desc', 5)] or '').strip() if col_map.get('desc') is not None else None
    
    # Clean up scale/unit
    if scale in ['-', '–', '']:
        scale = None
    if unit in ['-', '–', '']:
        unit = None
    
    # Clean description (remove newlines)
    if desc:
        desc = re.sub(r'\s+', ' ', desc).strip()
    
    return ConfigKey(
        name=name,
        key_id=key_id,
        data_type=dtype,
        group=extract_group_from_name(name),
        scale=scale,
        unit=unit,
        description=desc,
    )


def parse_enum_table(table: list) -> dict:
    """Parse an enum/constant table into a dict."""
    if not table or len(table) < 2:
        return {}
    
    # Find column indices
    header = table[0]
    col_map = {}
    for i, cell in enumerate(header):
        cell_lower = str(cell).lower() if cell else ''
        if 'constant' in cell_lower or 'name' in cell_lower:
            col_map['name'] = i
        elif 'value' in cell_lower:
            col_map['value'] = i
        elif 'description' in cell_lower:
            col_map['desc'] = i
    
    if 'name' not in col_map or 'value' not in col_map:
        return {}
    
    values = {}
    for row in table[1:]:
        if not row or len(row) <= max(col_map.values()):
            continue
        
        name = str(row[col_map['name']] or '').strip()
        value_str = str(row[col_map['value']] or '').strip()
        desc = str(row[col_map.get('desc', 2)] or '').strip() if col_map.get('desc') is not None else None
        
        if not name or not value_str:
            continue
        
        # Parse value (could be hex or decimal)
        try:
            if value_str.startswith('0x'):
                value = int(value_str, 16)
            else:
                value = int(value_str)
        except:
            continue
        
        values[name] = {
            'value': value,
            'description': desc if desc else None,
        }
    
    return {'values': values} if values else {}


def get_column_map(header: list) -> dict:
    """Map header columns to indices."""
    col_map = {}
    for i, cell in enumerate(header):
        cell_lower = str(cell).lower() if cell else ''
        if 'configuration' in cell_lower or (i == 0 and 'cfg' not in cell_lower):
            col_map['name'] = i
        elif 'key' in cell_lower and 'id' in cell_lower:
            col_map['key_id'] = i
        elif cell_lower == 'type' or 'type' in cell_lower:
            col_map['type'] = i
        elif 'scale' in cell_lower:
            col_map['scale'] = i
        elif 'unit' in cell_lower:
            col_map['unit'] = i
        elif 'description' in cell_lower:
            col_map['desc'] = i
    
    # Default mapping if headers not found
    if 'name' not in col_map:
        col_map = {'name': 0, 'key_id': 1, 'type': 2, 'scale': 3, 'unit': 4, 'desc': 5}
    
    return col_map


def extract_config_keys_from_text(text: str) -> list[ConfigKey]:
    """Extract config keys from page text using regex."""
    keys = []
    
    # Pattern: CFG-XXX-YYY 0xNNNNNNNN TYPE SCALE UNIT Description...
    # The description continues until the next CFG- or end of relevant section
    pattern = re.compile(
        r'(CFG-[A-Z0-9_-]+)\s+'           # Config key name
        r'(0x[0-9a-fA-F]{8})\s+'          # Key ID (8 hex digits)
        r'([ULEXI][0-9]?)\s+'             # Type (L, U1, U2, E1, X1, etc.)
        r'([0-9.e-]+|-)\s+'               # Scale (number or -)
        r'([a-zA-Z/%°·]+|-)\s+'           # Unit (letters or -)
        r'([^\n]+)',                       # Description (rest of line)
        re.MULTILINE
    )
    
    for match in pattern.finditer(text):
        name, key_id, dtype, scale, unit, desc = match.groups()
        
        # Clean up values
        scale = None if scale in ['-', '–'] else scale
        unit = None if unit in ['-', '–'] else unit
        desc = re.sub(r'\s+', ' ', desc).strip() if desc else None
        
        key = ConfigKey(
            name=name,
            key_id=key_id,
            data_type=dtype,
            group=extract_group_from_name(name),
            scale=scale,
            unit=unit,
            description=desc,
        )
        keys.append(key)
    
    return keys


def extract_enum_from_text(text: str, enum_keys: list[str]) -> dict[str, dict]:
    """Extract enum constants from text for specific keys."""
    enums = {}
    
    # Pattern for enum table: Constants for CFG-XXX-YYY
    # Followed by: NAME VALUE Description
    enum_header_pattern = re.compile(
        r'Constants for (CFG-[A-Z0-9_,\s-]+)',
        re.IGNORECASE
    )
    
    constant_pattern = re.compile(
        r'^([A-Z][A-Z0-9_]+)\s+'           # Constant name
        r'(0x[0-9a-fA-F]+|\d+)\s+'         # Value (hex or decimal)
        r'(.+)$',                           # Description
        re.MULTILINE
    )
    
    for match in enum_header_pattern.finditer(text):
        keys_str = match.group(1)
        # Extract key names from the header
        key_names = re.findall(r'CFG-[A-Z0-9_-]+', keys_str)
        
        # Find constants after this header
        start_pos = match.end()
        # Look for constants in the next ~500 chars
        search_text = text[start_pos:start_pos + 1000]
        
        values = {}
        for const_match in constant_pattern.finditer(search_text):
            const_name, value_str, desc = const_match.groups()
            
            # Skip if it looks like a config key
            if const_name.startswith('CFG-'):
                break
            
            try:
                value = int(value_str, 16) if value_str.startswith('0x') else int(value_str)
            except:
                continue
            
            values[const_name] = {
                'value': value,
                'description': desc.strip(),
            }
        
        if values:
            for key_name in key_names:
                enums[key_name] = {'values': values}
    
    return enums


def extract_config_keys_from_pdf(pdf_path: str) -> dict:
    """Extract all config keys from a PDF using text-based parsing."""
    pdf = pdfplumber.open(pdf_path)
    
    all_keys = []
    groups = {}
    all_enums = {}
    
    for page_num, page in enumerate(pdf.pages):
        text = page.extract_text() or ''
        
        # Skip pages without config keys
        if 'CFG-' not in text or '0x' not in text:
            continue
        
        # Extract config keys from text
        keys = extract_config_keys_from_text(text)
        all_keys.extend(keys)
        
        # Track groups
        for key in keys:
            if key.group not in groups:
                parsed = parse_key_id(key.key_id)
                groups[key.group] = {
                    'name': key.group,
                    'group_id': parsed.get('group_id', ''),
                }
        
        # Extract enums
        enum_keys = [k.name for k in keys if k.data_type.startswith('E') or k.data_type.startswith('X')]
        if enum_keys:
            page_enums = extract_enum_from_text(text, enum_keys)
            all_enums.update(page_enums)
    
    pdf.close()
    
    # Attach enums to keys
    for key in all_keys:
        if key.name in all_enums:
            key.inline_enum = all_enums[key.name]
    
    # Deduplicate keys by name (keep first occurrence)
    seen = set()
    unique_keys = []
    for key in all_keys:
        if key.name not in seen:
            seen.add(key.name)
            unique_keys.append(key)
    
    # Convert to output format
    keys_output = []
    for key in unique_keys:
        key_dict = {
            'name': key.name,
            'key_id': key.key_id,
            'group': key.group,
            'data_type': key.data_type,
        }
        if key.scale:
            key_dict['scale'] = key.scale
        if key.unit:
            key_dict['unit'] = key.unit
        if key.description:
            key_dict['description'] = key.description
        if key.inline_enum:
            key_dict['inline_enum'] = key.inline_enum
        
        keys_output.append(key_dict)
    
    return {
        'schema_version': '1.0',
        'source_document': {
            'filename': Path(pdf_path).name,
        },
        'groups': groups,
        'keys': keys_output,
        '_stats': {
            'total_keys': len(keys_output),
            'total_groups': len(groups),
        }
    }


def process_pdf(pdf_path: str, output_path: str = None):
    """Process a PDF and save extracted config keys."""
    print(f'Processing: {Path(pdf_path).name}')
    
    result = extract_config_keys_from_pdf(pdf_path)
    
    if output_path is None:
        output_path = f'extracted/{Path(pdf_path).stem}_config_keys.json'
    
    Path(output_path).parent.mkdir(exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f'  Saved: {output_path}')
    print(f'  Stats: {result["_stats"]}')
    
    return result


if __name__ == '__main__':
    import sys
    
    # Default: process F9 HPG 1.51
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        pdf_path = 'interface_manuals/zed-f9p-module/u-blox-F9-HPG-1.51_InterfaceDescription_UBXDOC-963802114-13124.pdf'
    
    process_pdf(pdf_path)
