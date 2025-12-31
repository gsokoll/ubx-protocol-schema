"""Extraction prompts for UBX configuration keys.

Config keys appear in F9+ generation manuals in tables with columns:
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

# Valid data types for config keys
CONFIG_KEY_DATA_TYPES = [
    "L",      # Boolean (1 bit)
    "U1", "I1", "X1", "E1",  # 1-byte types
    "U2", "I2", "X2", "E2",  # 2-byte types
    "U4", "I4", "X4", "E4", "R4",  # 4-byte types
    "U8", "I8", "R8",  # 8-byte types
]

# Base prompt for config key extraction
BASE_CONFIG_KEY_PROMPT = """You are extracting UBX configuration key definitions from u-blox PDF manual pages.

TARGET GROUP: {group_name}
{group_description}

CONTEXT: Configuration keys are used with CFG-VALGET/VALSET/VALDEL messages to configure u-blox receivers. Each key has a unique 32-bit ID and stores a typed value.

CONFIG KEY TABLE FORMAT:
The PDF shows a table titled "Table N: {group_name} configuration items" with columns:
- Configuration item: Full key name (e.g., {group_name}-EXAMPLE)
- Key ID: 32-bit hex value (0xNNNNNNNN)
- Type: Data type (L, U1, U2, U4, I4, X1, X2, X4, E1, E2, E4, R4, R8)
- Scale: Scaling factor or "-"
- Unit: Physical unit or "-"
- Description: What the key does

CRITICAL: Extract EVERY row from the configuration items table for {group_name}.
Do NOT skip any keys. Do NOT include keys from other groups.

EXTRACTION RULES:

1. KEY NAME: Must start with "{group_name}-" and match exactly what's in the PDF

2. KEY ID: Must be 8 hex digits (0xNNNNNNNN)

3. DATA TYPE: Extract exactly as shown:
   - L = Boolean (true/false)
   - U1/U2/U4/U8 = Unsigned integers
   - I1/I2/I4/I8 = Signed integers  
   - X1/X2/X4 = Bitfields
   - E1/E2/E4 = Enumerated values
   - R4/R8 = Floating point

4. SCALE: If shown (e.g., "1e-7", "2^-5"), include as string. Omit if "-".

5. UNIT: Physical unit if shown (ms, deg, m, Hz, %). Omit if "-".

6. DESCRIPTION: Clean, single-line description.

7. ENUMERATIONS (E-type keys): 
   Look for "Constants for {group_name}-XXX" tables after the key.
   Extract each constant with: name, numeric value, description.

8. BITFIELDS (X-type keys):
   Look for bit definition tables showing individual bits.
   Extract each bit with: name, bit_start, bit_end, description.

Extract ALL configuration keys for {group_name} from the table on these pages.
Use the config_key_extraction tool to return the results.
"""

# Prompt addition for enum-heavy pages
ENUM_GUIDANCE = """
ENUM EXTRACTION (CRITICAL for this group):
This group contains enumerated (E-type) keys. For each E-type key:
1. Find the associated "Constants for CFG-XXX" table (usually immediately after the key definition)
2. Extract ALL constant values with their numeric values and descriptions
3. Constant names are usually ALL_CAPS with underscores
4. Values can be decimal or hex (0x prefix)

Example enum structure:
{
  "inline_enum": {
    "values": {
      "PORTABLE": {"value": 0, "description": "Portable mode"},
      "STATIONARY": {"value": 2, "description": "Stationary mode"}
    }
  }
}
"""

# Prompt addition for bitfield-heavy groups
BITFIELD_GUIDANCE = """
BITFIELD EXTRACTION (CRITICAL for this group):
This group contains bitfield (X-type) keys. For each X-type key:
1. Find the bit definition table (usually shows Bit, Name, Description columns)
2. Extract each defined bit with its position and meaning
3. Bits can be single (bit 0) or ranges (bits 4..7)
4. Reserved bits can be noted but are optional to extract

Example bitfield structure:
{
  "bitfield": {
    "bits": [
      {"name": "enable", "bit_start": 0, "bit_end": 0, "description": "Enable feature"},
      {"name": "mode", "bit_start": 1, "bit_end": 2, "description": "Operating mode"}
    ]
  }
}
"""

# Groups known to have many enums
ENUM_HEAVY_GROUPS = {
    "CFG-NAVSPG",  # Dynamic model, fix mode
    "CFG-NMEA",    # NMEA version, talker IDs
    "CFG-SIGNAL",  # GNSS signal selection
    "CFG-RATE",    # Time reference
    "CFG-ODO",     # Odometer profile
    "CFG-GEOFENCE",  # Geofence states
    "CFG-PM",      # Power management modes
    "CFG-TXREADY",  # TX ready modes
}

# Groups known to have many bitfields
BITFIELD_HEAVY_GROUPS = {
    "CFG-HW",      # Hardware pin configs
    "CFG-UART1", "CFG-UART2", "CFG-USB", "CFG-SPI", "CFG-I2C",  # Port protocols
    "CFG-INFMSG",  # Info message enables
    "CFG-ITFM",    # Interference monitor
    "CFG-SBAS",    # SBAS settings
    "CFG-QZSS",    # QZSS settings
    "CFG-NAVHPG",  # High precision settings
    "CFG-TMODE",   # Time mode settings
}


def build_config_key_prompt(
    group_name: str,
    group_description: str = "",
) -> str:
    """Build an extraction prompt for a specific config key group.
    
    Args:
        group_name: Config group name (e.g., "CFG-RATE")
        group_description: Optional description of the group
    
    Returns:
        Extraction prompt tailored to the group
    """
    desc_line = f"Description: {group_description}" if group_description else ""
    
    prompt = BASE_CONFIG_KEY_PROMPT.format(
        group_name=group_name,
        group_description=desc_line,
    )
    
    # Add enum guidance for enum-heavy groups
    if group_name in ENUM_HEAVY_GROUPS:
        prompt += ENUM_GUIDANCE
    
    # Add bitfield guidance for bitfield-heavy groups  
    if group_name in BITFIELD_HEAVY_GROUPS:
        prompt += BITFIELD_GUIDANCE
    
    return prompt


def build_config_key_tool_schema() -> dict:
    """Build the tool schema for config key extraction.
    
    Returns JSON schema for extracting all keys from pages.
    """
    return {
        "name": "config_key_extraction",
        "description": "Extract ALL configuration key definitions from PDF pages into a flat list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "description": "List of configuration keys extracted",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Full key name (e.g., 'CFG-RATE-MEAS')"
                            },
                            "key_id": {
                                "type": "string",
                                "pattern": "^0x[0-9a-fA-F]{8}$",
                                "description": "32-bit key ID as hex"
                            },
                            "data_type": {
                                "type": "string",
                                "enum": CONFIG_KEY_DATA_TYPES,
                                "description": "Data type"
                            },
                            "description": {
                                "type": "string",
                                "description": "Key description"
                            },
                            "scale": {
                                "type": "string",
                                "description": "Scale factor as string (e.g., '1e-7', '2^-5')"
                            },
                            "unit": {
                                "type": "string",
                                "description": "Physical unit (e.g., 'ms', 'deg')"
                            },
                            "default_value": {
                                "oneOf": [
                                    {"type": "boolean"},
                                    {"type": "integer"},
                                    {"type": "number"},
                                    {"type": "string"}
                                ],
                                "description": "Default value if shown"
                            },
                            "inline_enum": {
                                "type": "object",
                                "description": "Enumeration for E-type keys",
                                "properties": {
                                    "values": {
                                        "type": "object",
                                        "additionalProperties": {
                                            "type": "object",
                                            "properties": {
                                                "value": {"type": "integer"},
                                                "description": {"type": "string"}
                                            },
                                            "required": ["value"]
                                        }
                                    }
                                }
                            },
                            "bitfield": {
                                "type": "object",
                                "description": "Bitfield definition for X-type keys",
                                "properties": {
                                    "bits": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "name": {"type": "string"},
                                                "bit_start": {"type": "integer"},
                                                "bit_end": {"type": "integer"},
                                                "description": {"type": "string"}
                                            },
                                            "required": ["name", "bit_start", "bit_end"]
                                        }
                                    }
                                }
                            }
                        },
                        "required": ["name", "key_id", "data_type"]
                    }
                }
            },
            "required": ["keys"]
        }
    }
