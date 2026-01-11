"""
UBX Protocol Knowledge Base for Validation Prompts.

Contains accumulated knowledge about:
- UBX protocol structure and conventions
- Known gotchas and extraction pitfalls
- Version variation patterns
- Data type mappings
"""

# Core UBX protocol knowledge
UBX_PROTOCOL_OVERVIEW = """
## UBX Protocol Structure

UBX is u-blox's proprietary binary protocol for GNSS receivers.

### Frame Format
```
┌──────┬──────┬───────┬────────┬─────────┬─────────┬──────────┐
│ Sync │ Sync │ Class │ Msg ID │ Length  │ Payload │ Checksum │
│ 0xB5 │ 0x62 │ 1byte │ 1byte  │ 2bytes  │ N bytes │ 2 bytes  │
└──────┴──────┴───────┴────────┴─────────┴─────────┴──────────┘
```

### Data Types (Little-Endian)
| Type | Size | Description |
|------|------|-------------|
| U1, U2, U4, U8 | 1-8 bytes | Unsigned integers |
| I1, I2, I4, I8 | 1-8 bytes | Signed integers (2's complement) |
| R4, R8 | 4, 8 bytes | IEEE 754 floats |
| X1, X2, X4 | 1-4 bytes | Bitfields (must have bitfield definition) |
| CH | 1 byte | ASCII character |

### Message Classes
| Class | ID | Description |
|-------|-----|-------------|
| NAV | 0x01 | Navigation results |
| RXM | 0x02 | Receiver manager |
| INF | 0x04 | Information |
| ACK | 0x05 | Acknowledgments |
| CFG | 0x06 | Configuration |
| UPD | 0x09 | Firmware update |
| MON | 0x0A | Monitoring |
| AID | 0x0B | AssistNow (deprecated) |
| TIM | 0x0D | Timing |
| ESF | 0x10 | External sensor fusion |
| MGA | 0x13 | Multiple GNSS assistance |
| LOG | 0x21 | Logging |
| SEC | 0x27 | Security |
| HNR | 0x28 | High-rate navigation |
"""

# Known gotchas and extraction pitfalls
EXTRACTION_GOTCHAS = """
## Known Extraction Gotchas

### 1. Bitfield Types (X1, X2, X4)
- X-type fields MUST have a bitfield definition with named bits
- Common mistake: Using U1/U2/U4 instead of X1/X2/X4 for flag fields
- Fields named "flags", "mask", "status", "cfg" are usually bitfields

### 2. Array Detection
- PDF shows: "U1[6]", "U1 x 6", "CH[30]" → `{"array_of": "U1", "count": 6}`
- Offset gaps reveal arrays: offset 4 to 8 with U1 type = 4-element array
- Reserved fields often span multiple bytes

### 3. Variable-Length Payloads
- Must use `repeated_groups` for variable trailing data, NOT regular fields
- `repetition_type`: "count_field" (uses numSvs, numCh, etc.) or "fill_remaining"
- Formula in length.variable.formula should match repeated group size

### 4. Multi-Variant Messages
- Same Class/Message ID can have different payloads
- Discriminators: payload_length, version field at offset 0, type field
- Examples: UBX-CFG-PRT (by portId), UBX-MGA-* (by type), UBX-RXM-PMREQ (v0 vs v1)

### 5. Reserved Fields
- Mark with `"reserved": true`
- Often named "reserved0", "reserved1", etc.
- Size determined by offset gap to next field

### 6. Scale Factors
- Include both "raw" (human-readable like "2^-7") and "multiplier" (numeric)
- Common scales: 1e-7 (degrees), 1e-5, 1e-2, 2^-N for fixed-point

### 7. Conditional Interpretation
- Some fields change meaning based on flags (e.g., ECEF vs LLA coordinates)
- Use `conditional_interpretation` with selector_field reference
"""

# Version variation patterns
VERSION_PATTERNS = """
## Version Variation Patterns

### Protocol Version Differences
- M8 (protocol 15-23): Older message set, AID-* messages, simpler structures
- F9 (protocol 27+): CFG-VAL* configuration, more complex messages
- M10/F10 (protocol 32+): Extended features, new message variants

### Common Variations
1. **Field additions**: Later versions add fields at end of payload
2. **Bitfield expansion**: New bits defined in existing X-type fields
3. **Version field**: Messages with `version` at offset 0 indicate structural changes
4. **Transaction support**: CFG-VAL* messages gained `transaction` field in later firmware

### How to Handle
- If structure differs but both are valid for their version → `valid_variation`
- If one is clearly wrong (missing fields, wrong offsets) → fix the canonical
- Document version-specific differences in `version_specific` field
"""

# Config key knowledge
CONFIG_KEY_KNOWLEDGE = """
## Configuration Key Knowledge (CFG-VAL*)

### Key ID Structure
32-bit key ID encodes:
- Bits 31-28: Reserved (0)
- Bits 27-20: Group ID
- Bits 19-16: Reserved (0)  
- Bits 15-12: Size indicator (1=1byte, 2=2byte, 4=4byte, 8=8byte)
- Bits 11-0: Item ID within group

### Data Types
| Size | Types |
|------|-------|
| L (1 bit) | Boolean stored in U1 |
| U1, I1, E1, X1 | 1 byte |
| U2, I2, E2, X2 | 2 bytes |
| U4, I4, R4, E4, X4 | 4 bytes |
| U8, I8, R8 | 8 bytes |

### Layers
- RAM (0x01): Volatile, lost on reset
- BBR (0x02): Battery-backed RAM, survives reset
- Flash (0x04): Non-volatile, survives power cycle
- Default (0x07): Factory defaults (read-only)

### Common Issues
- OCR errors: "I2C" misread as "12C", hex values corrupted
- Scale factors may differ between interface description versions
- Some keys are device-family specific (F9 vs M10)
"""

# Validation prompt template
VALIDATION_PROMPT_TEMPLATE = """
You are validating a UBX protocol message definition against PDF manual pages.

{ubx_overview}

{gotchas}

{version_patterns}

## MANUAL CONTEXT
{manual_context}

## YOUR TASK

Compare this CANONICAL message definition against the PDF pages shown.

### CANONICAL DEFINITION:
```json
{canonical_json}
```

### VALIDATION CHECKLIST:
1. **Name & IDs**: Do class_id and message_id match?
2. **Payload Length**: Does the length specification match?
3. **Fields**: For each field, verify:
   - Name matches (case-insensitive OK, but note differences)
   - byte_offset is correct
   - data_type matches (watch for X vs U types)
   - Arrays have correct count
4. **Bitfields**: If X-type, verify bit definitions match
5. **Repeated Groups**: If variable payload, verify group structure
6. **Scale/Units**: Verify scale factors and units if present

### RESPONSE FORMAT:
Return a JSON object:
```json
{{
  "matches": true | false,
  "confidence": "high" | "medium" | "low",
  "discrepancies": [
    {{
      "field": "fieldName",
      "issue": "description of mismatch",
      "canonical_value": "what canonical says",
      "pdf_value": "what PDF shows"
    }}
  ],
  "notes": "any relevant observations about version differences, etc."
}}
```

If the message is not present in this manual, return:
```json
{{
  "matches": null,
  "confidence": "high",
  "discrepancies": [],
  "notes": "Message not present in this manual"
}}
```
"""

CONFIG_KEY_VALIDATION_TEMPLATE = """
You are validating UBX configuration key definitions against PDF manual pages.

{ubx_overview}

{config_key_knowledge}

## YOUR TASK

Compare these CANONICAL configuration key definitions against the PDF pages shown.

### CANONICAL DEFINITIONS:
```json
{canonical_json}
```

### VALIDATION CHECKLIST:
1. **Key Name**: Does the name match exactly?
2. **Key ID**: Does the hex key ID match?
3. **Data Type**: Does the type match?
4. **Description**: Is the meaning the same?
5. **Scale/Unit**: If present, do they match?
6. **Enumeration**: If enum type, do values match?

### RESPONSE FORMAT:
Return a JSON object:
```json
{{
  "matches": true | false,
  "confidence": "high" | "medium" | "low",
  "discrepancies": [
    {{
      "key": "CFG-KEY-NAME",
      "issue": "description of mismatch",
      "canonical_value": "what canonical says",
      "pdf_value": "what PDF shows"
    }}
  ],
  "notes": "any relevant observations"
}}
```
"""


def build_message_validation_prompt(
    canonical_json: str,
    device_family: str | None = None,
    protocol_version: int | None = None,
    firmware_version: str | None = None,
) -> str:
    """Build a complete validation prompt for a message.
    
    Args:
        canonical_json: The canonical message definition as JSON
        device_family: Device family (M8, F9, M10, etc.)
        protocol_version: Protocol version as integer (e.g., 2700 for 27.00)
        firmware_version: Firmware version string
    """
    # Build manual context section
    if device_family or protocol_version or firmware_version:
        context_parts = []
        if device_family:
            context_parts.append(f"- **Device Family**: {device_family}")
        if protocol_version:
            major = protocol_version // 100
            minor = protocol_version % 100
            context_parts.append(f"- **Protocol Version**: {major}.{minor:02d}")
        if firmware_version:
            context_parts.append(f"- **Firmware**: {firmware_version}")
        
        manual_context = "\n".join(context_parts)
        manual_context += """

Consider version differences when validating:
- M8 devices (protocol 15-23): Older message set, may lack newer fields
- F9/M9 devices (protocol 27-35): CFG-VAL* configuration, extended features
- M10/F10 devices (protocol 34+): Latest features

If the PDF shows a different structure that's valid for this protocol version,
note it as a valid variation rather than a discrepancy."""
    else:
        manual_context = "No version metadata available for this manual."
    
    return VALIDATION_PROMPT_TEMPLATE.format(
        ubx_overview=UBX_PROTOCOL_OVERVIEW,
        gotchas=EXTRACTION_GOTCHAS,
        version_patterns=VERSION_PATTERNS,
        manual_context=manual_context,
        canonical_json=canonical_json,
    )


def build_config_key_validation_prompt(canonical_json: str) -> str:
    """Build a complete validation prompt for config keys."""
    return CONFIG_KEY_VALIDATION_TEMPLATE.format(
        ubx_overview=UBX_PROTOCOL_OVERVIEW,
        config_key_knowledge=CONFIG_KEY_KNOWLEDGE,
        canonical_json=canonical_json,
    )


# Bitfield extraction prompt - specialized for extracting bit-level details
BITFIELD_EXTRACTION_TEMPLATE = """
You are extracting bitfield definitions from a UBX protocol PDF manual.

## TASK

Extract the COMPLETE bitfield definition for field "{field_name}" in message {message_name}.

This field has data type {data_type}, which means it is a {bit_count}-bit bitfield.

## WHAT TO LOOK FOR

In the PDF, find the table or description that shows the bit-level breakdown of this field.
Look for:
1. A table with columns like "Bit", "Name", "Description"
2. Inline descriptions like "Bit 0: gnssFixOk", "Bits 4-5: carrSoln"
3. Reserved bits (often shown as "reserved" or left blank)

## EXTRACTION RULES

1. **Bit positions**: Use 0-based indexing (Bit 0 is the LSB)
2. **Multi-bit fields**: Record the starting bit and width
   - Example: "Bits 4-5" → bit_offset: 4, width: 2
3. **Reserved bits**: Include them with name "reserved" or "reservedN"
4. **All bits must be accounted for**: Total bits must equal {bit_count}

## RESPONSE FORMAT

Return a JSON object with the extracted bitfield:
```json
{{
  "field_name": "{field_name}",
  "data_type": "{data_type}",
  "bits_total": {bit_count},
  "bitfield": [
    {{
      "name": "<bit_name>",
      "bit_offset": <0-based starting bit>,
      "width": <number of bits>,
      "description": "<brief description>"
    }},
    ...
  ],
  "extraction_confidence": "high" | "medium" | "low",
  "notes": "<any observations about the extraction>"
}}
```

If the bitfield definition is NOT found in the PDF:
```json
{{
  "field_name": "{field_name}",
  "error": "bitfield_not_found",
  "notes": "<what you found instead or why it's missing>"
}}
```

## EXAMPLE

For a field "flags" of type X1 (8 bits), a correct extraction might be:
```json
{{
  "field_name": "flags",
  "data_type": "X1",
  "bits_total": 8,
  "bitfield": [
    {{"name": "gnssFixOk", "bit_offset": 0, "width": 1, "description": "Valid fix"}},
    {{"name": "diffSoln", "bit_offset": 1, "width": 1, "description": "Differential corrections applied"}},
    {{"name": "reserved", "bit_offset": 2, "width": 1, "description": "Reserved"}},
    {{"name": "psmState", "bit_offset": 3, "width": 3, "description": "Power save mode state"}},
    {{"name": "headVehValid", "bit_offset": 6, "width": 1, "description": "Heading of vehicle valid"}},
    {{"name": "carrSoln", "bit_offset": 7, "width": 1, "description": "Carrier phase solution"}}
  ],
  "extraction_confidence": "high",
  "notes": "All 8 bits accounted for"
}}
```
"""


# Message extraction prompt - for extracting complete message definitions
MESSAGE_EXTRACTION_TEMPLATE = """
You are extracting a complete UBX message definition from a PDF manual.

{ubx_overview}

## TASK

Extract the COMPLETE definition for message {message_name} from the PDF pages provided.

## EXTRACTION CHECKLIST

1. **Message Header**
   - Class ID (hex, e.g., 0x01)
   - Message ID (hex, e.g., 0x07)
   - Message type: "output", "input", "poll", or "command"

2. **Payload Structure**
   - Fixed or variable length
   - If variable: what determines the length (count field, fill remaining)

3. **Fields** - For EACH field extract:
   - name (exact spelling from PDF)
   - byte_offset (0-based)
   - data_type (U1, I2, X4, R8, CH, etc.)
   - description
   - For arrays: the count or "variable"
   - For X-types: the bitfield definition (see below)
   - For scaled values: scale factor and unit

4. **Bitfields** - For EVERY X-type field (X1, X2, X4):
   - Extract the complete bit-level definition
   - Include ALL bits (including reserved)
   - Use 0-based bit offsets

5. **Repeated Groups** - If payload has variable trailing data:
   - Identify the count field
   - Define the repeating structure

## RESPONSE FORMAT

```json
{{
  "name": "{message_name}",
  "class_id": "0x01",
  "message_id": "0x07",
  "message_type": "output",
  "description": "<message description>",
  "payload": {{
    "length": {{"fixed": <bytes>}} or {{"variable": {{"formula": "8 + N * 12"}}}},
    "fields": [
      {{
        "name": "<field_name>",
        "byte_offset": <number>,
        "data_type": "<type>",
        "description": "<description>",
        "bitfield": [...],  // REQUIRED for X-types
        "scale": {{"raw": "1e-7", "multiplier": 0.0000001}},  // if applicable
        "unit": "degrees"  // if applicable
      }},
      ...
    ],
    "repeated_groups": [...]  // if applicable
  }},
  "extraction_confidence": "high" | "medium" | "low"
}}
```
"""


def build_bitfield_extraction_prompt(
    message_name: str,
    field_name: str,
    data_type: str,
) -> str:
    """Build a prompt for extracting a specific bitfield definition."""
    # Determine bit count from data type
    bit_counts = {"X1": 8, "X2": 16, "X4": 32, "X8": 64}
    bit_count = bit_counts.get(data_type, 8)

    return BITFIELD_EXTRACTION_TEMPLATE.format(
        message_name=message_name,
        field_name=field_name,
        data_type=data_type,
        bit_count=bit_count,
    )


def build_message_extraction_prompt(message_name: str) -> str:
    """Build a prompt for extracting a complete message definition."""
    return MESSAGE_EXTRACTION_TEMPLATE.format(
        ubx_overview=UBX_PROTOCOL_OVERVIEW,
        message_name=message_name,
    )
