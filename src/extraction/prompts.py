"""Modular extraction prompts for UBX message extraction.

Separates base extraction logic from message-specific guidance to:
1. Keep prompts focused and shorter
2. Add specific guidance only when needed
3. Improve extraction accuracy for known problem areas

Architecture:
- BASE_PROMPT: Core extraction logic (always included)
- ARRAY_GUIDANCE / BITFIELD_GUIDANCE: Added for messages with known issues
- DEDICATED_PROMPTS: Complete custom prompts for challenging messages
- VARIANT_GUIDANCE: Short additions for variant messages
- ENUM_GUIDANCE: Hints for known enumeration fields
"""

import json
from pathlib import Path
from functools import lru_cache

# Enumeration guidance - hints for known enum fields
ENUM_GUIDANCE = """
KNOWN ENUMERATIONS:
The following field names have known enumeration values. Use these as guidance, but note:
- Values may vary by firmware/protocol version
- Not all values may be supported on all devices
- The PDF may show additional or different values - extract what you see

{enum_hints}

When extracting these fields, include an "enumeration" object with the values you find in the PDF.
"""

# Base prompt - always included, focused on core extraction
BASE_PROMPT = """You are extracting a UBX protocol message definition from u-blox PDF manual pages.

TARGET MESSAGE: {message_name}{anchor}

CRITICAL INSTRUCTIONS:
1. Extract ONLY the message named "{message_name}". Ignore any other messages visible.
2. The payload table shows fields in order. Extract them exactly as shown with correct byte offsets.
3. Verify field sizes match offset differences (e.g., if offset jumps by 4, field is 4 bytes).

FIELD EXTRACTION:
- byte_offset: Exact byte offset from "Offset" column (integer, 0-indexed)
- data_type: UBX types: U1, I1, X1, U2, I2, X2, U4, I4, X4, R4, R8, CH
- For arrays: {{"array_of": "U1", "count": N}} - check Type column for "[N]" or "x N"
- scale: Include "raw" string and numeric "multiplier" if shown
- unit: Physical unit if shown (ms, deg, m/s, etc.)
- reserved: Set true for reserved fields

PAYLOAD LENGTH:
- Fixed: {{"fixed": 28}}
- Variable: {{"variable": {{"base": 8, "formula": "8 + N*12"}}}}

QUALITY CHECK before returning:
- Byte offsets sequential and non-overlapping
- Field sizes match offset gaps
- Total field sizes match payload length
"""

# Array detection emphasis - for messages with array extraction errors
ARRAY_GUIDANCE = """
ARRAY DETECTION (CRITICAL):
- Type column shows arrays: "U1[6]", "U1 x 6", "CH[30]" = {{"array_of": "U1", "count": 6}}
- Offset gaps reveal arrays: offset 4 to 8 with U1 type = {{"array_of": "U1", "count": 4}}
- Reserved fields often span multiple bytes - verify size from offset difference
- String fields (CH) are usually arrays: {{"array_of": "CH", "count": N}}
"""

# Bitfield detection emphasis - for messages with X vs U type confusion
BITFIELD_GUIDANCE = """
BITFIELD TYPE DETECTION (CRITICAL):
- Use X1/X2/X4 (NOT U1/U2/U4) when:
  - Field named "flags", "mask", "status", "cfg", "supported", "enabled"
  - Description mentions "bitfield" or lists bit meanings
  - Sub-table shows bit positions
- Extract bitfield structure for ALL X-type fields
"""

# Variant message guidance - only for known variant messages
VARIANT_GUIDANCE = {
    "UBX-LOG-FINDTIME": """
UBX-LOG-FINDTIME has TWO structures:
- INPUT: version, type, year, month, day, hour, minute, second, reserved
- OUTPUT: version, type, reserved, entryNumber
Extract based on message name suffix (-INPUT or -OUTPUT).
""",
    
    "UBX-RXM-RLM": """
UBX-RXM-RLM has TWO structures based on "type" field:
- SHORT (type=0x01, 16 bytes): version, type, svId, reserved0, beacon[8], message, params[2], reserved1
- LONG (type=0x02, 28 bytes): version, type, svId, reserved0, beacon[8], message, params[12]
Extract based on message name suffix (-SHORT or -LONG).
""",
    
    "UBX-RXM-PMREQ": """
UBX-RXM-PMREQ has TWO structures:
- V0 (8 bytes): duration (U4), flags (X4) - NO version field
- V1 (16 bytes): version (U1), reserved0[3], duration (U4), flags (X4), wakeupSources (X4)
Check payload length to determine version. Extract based on suffix (-V0 or -V1).
""",
    
    "UBX-TIM-VCOCAL": """
UBX-TIM-VCOCAL has TWO structures:
- SET (input, 1 byte): type field only
- GET (output, 12 bytes): type, version, oscId, reserved, gainUncertainty, gainVco
Extract based on message name suffix (-SET or -GET).
""",
    
    "UBX-CFG-DAT": """
UBX-CFG-DAT has THREE structures:
- POLL (0 bytes): empty payload
- SET (52 bytes): majA, flat, dX, dY, dZ, rotX, rotY, rotZ, scale
- GET (52 bytes): datumNum, datumName[6], majA, flat, dX, dY, dZ, rotX, rotY, rotZ, scale
Extract based on message name suffix (-POLL, -SET, or -GET).
""",

    "UBX-MON-GNSS": """
UBX-MON-GNSS has TWO structures:
- V0 (8 bytes, version=0x00): version, supported, defaultGnss, enabled, simultaneous, reserved
- V1 (variable, version=0x01): version, numPlans, activePlanInfo, repeated group with signal plans
Check if numPlans field exists to determine version. Name as UBX-MON-GNSS-V0 or UBX-MON-GNSS-V1.
""",

    "UBX-NAV-RELPOSNED": """
UBX-NAV-RELPOSNED has TWO structures:
- V0 (40 bytes): version=0x00, relPosHPN at offset 20, flags at offset 36
- V1 (64 bytes): version=0x01, relPosLength at offset 20, flags at offset 60
Check payload length: 40 bytes = V0, 64 bytes = V1.
""",

    "UBX-MGA-INI-TIME-UTC": """
UBX-MGA-INI-TIME-UTC (24 bytes): type, version, ref, leapSecs, year, month, day, hour, minute, second, reserved0, ns, tAccS, reserved1[2], tAccNs.
IMPORTANT: reserved1 at offset 18 is a 2-byte array U1[2], NOT two separate fields.
""",

    "UBX-MGA-INI-TIME-GNSS": """
UBX-MGA-INI-TIME-GNSS (24 bytes): type, version, ref, gnssId, reserved0[2], week, tow, ns, tAccS, reserved1[2], tAccNs.
IMPORTANT: reserved0 at offset 4 is U1[2] and reserved1 at offset 18 is U1[2] - arrays, NOT separate fields.
""",

    "UBX-SEC-SIG": """
UBX-SEC-SIG reports signal security information. Structure depends on version:
- v1 (12 bytes): version@0, reserved0[3]@1, jamFlags@4, reserved1[3]@5, spfFlags@8, reserved2[3]@9
- v2 (variable): version@0, sigSecFlags@1, reserved@2, jamNumCentFreqs@3, then jamming/spoofing data

IMPORTANT: Each field has ONE definition at ONE offset. Do NOT extract the same offset twice.
If the PDF shows both V0 and V1 variants, extract ONLY the structure that matches this manual's version.
""",

    "UBX-RXM-PMREQ": """
UBX-RXM-PMREQ has TWO completely different structures. Extract ONLY ONE based on what the PDF shows:

1. V0 format (8 bytes, NO version field): duration@0(U4), flags@4(X4)
2. V1 format (16 bytes, HAS version field): version@0(U1), reserved0[3]@1, duration@4(U4), flags@8(X4), wakeupSources@12(X4)

CRITICAL: Do NOT mix fields from both formats. If you see a version field at offset 0, use V1 format.
If duration is at offset 0, use V0 format.
""",
}

# Dedicated prompts for challenging messages - complete replacement prompts
# These are used INSTEAD of BASE_PROMPT for specific messages
DEDICATED_PROMPTS = {
    "UBX-LOG-FINDTIME": """You are extracting UBX-LOG-FINDTIME from u-blox PDF manual pages.

This message has TWO COMPLETELY DIFFERENT payload structures. You MUST extract only ONE:

**UBX-LOG-FINDTIME-INPUT (Request, 12 bytes):**
| Offset | Type | Name | Description |
|--------|------|------|-------------|
| 0 | U1 | version | Message version (0) |
| 1 | U1 | type | Message type (0=request) |
| 2 | U2 | year | Year (1-65635) |
| 4 | U1 | month | Month (1-12) |
| 5 | U1 | day | Day (1-31) |
| 6 | U1 | hour | Hour (0-23) |
| 7 | U1 | minute | Minute (0-59) |
| 8 | U1 | second | Second (0-60) |
| 9 | U1[3] | reserved | Reserved |

**UBX-LOG-FINDTIME-OUTPUT (Response, 8 bytes):**
| Offset | Type | Name | Description |
|--------|------|------|-------------|
| 0 | U1 | version | Message version (1) |
| 1 | U1 | type | Message type (1=response) |
| 2 | U1[2] | reserved | Reserved |
| 4 | U4 | entryNumber | Index of log entry |

Extract based on the message name suffix:
- "UBX-LOG-FINDTIME-INPUT" or "UBX-LOG-FINDTIME" → INPUT structure (12 bytes)
- "UBX-LOG-FINDTIME-OUTPUT" → OUTPUT structure (8 bytes)

Do NOT merge both structures. Return using ubx_message_extraction tool.
""",

    "UBX-RXM-RLM": """You are extracting UBX-RXM-RLM from u-blox PDF manual pages.

This message has TWO payload structures based on the "type" field:

**UBX-RXM-RLM-SHORT (type=0x01, 16 bytes):**
| Offset | Type | Name |
|--------|------|------|
| 0 | U1 | version |
| 1 | U1 | type (0x01) |
| 2 | U1 | svId |
| 3 | U1 | reserved0 |
| 4 | U1[8] | beacon |
| 12 | U1 | message |
| 13 | U1[2] | params |
| 15 | U1 | reserved1 |

**UBX-RXM-RLM-LONG (type=0x02, 28 bytes):**
| Offset | Type | Name |
|--------|------|------|
| 0 | U1 | version |
| 1 | U1 | type (0x02) |
| 2 | U1 | svId |
| 3 | U1 | reserved0 |
| 4 | U1[8] | beacon |
| 12 | U1 | message |
| 13 | U1[12] | params |
| 25 | U1[3] | reserved1 |

Extract based on message name suffix:
- "UBX-RXM-RLM-SHORT" or "UBX-RXM-RLM" → SHORT structure (16 bytes)
- "UBX-RXM-RLM-LONG" → LONG structure (28 bytes)

Do NOT merge both structures. Return using ubx_message_extraction tool.
""",

    "UBX-RXM-PMREQ": """You are extracting UBX-RXM-PMREQ from u-blox PDF manual pages.

This message has TWO payload structures based on firmware version:

**UBX-RXM-PMREQ-V0 (8 bytes, older firmware):**
| Offset | Type | Name | Description |
|--------|------|------|-------------|
| 0 | U4 | duration | Duration of power save mode (ms) |
| 4 | X4 | flags | Task flags |

**UBX-RXM-PMREQ-V1 (16 bytes, newer firmware):**
| Offset | Type | Name | Description |
|--------|------|------|-------------|
| 0 | U1 | version | Message version (0x00) |
| 1 | U1[3] | reserved0 | Reserved |
| 4 | U4 | duration | Duration of power save mode (ms) |
| 8 | X4 | flags | Task flags |
| 12 | X4 | wakeupSources | Wakeup sources |

CRITICAL: V0 has NO version field - it starts with duration!
CRITICAL: flags is X4 (bitfield), NOT U4!

Extract based on message name suffix or payload length:
- "UBX-RXM-PMREQ-V0" or 8-byte payload → V0 structure
- "UBX-RXM-PMREQ-V1" or 16-byte payload → V1 structure

Do NOT merge both structures. Return using ubx_message_extraction tool.
""",

    "UBX-CFG-VALSET": """You are extracting UBX-CFG-VALSET from u-blox PDF manual pages.

This message structure varies by firmware version:

**Newer versions (F9 HPG 1.50+):**
| Offset | Type | Name | Description |
|--------|------|------|-------------|
| 0 | U1 | version | Message version |
| 1 | U1 | layers | Configuration layers |
| 2 | U1 | transaction | Transaction mode (0=none, 1=begin, 2=continue, 3=end) |
| 3 | U1 | reserved0 | Reserved |
| 4+ | ... | cfgData | Configuration data (key-value pairs) |

**Older versions:**
| Offset | Type | Name | Description |
|--------|------|------|-------------|
| 0 | U1 | version | Message version |
| 1 | U1 | layers | Configuration layers |
| 2 | U1[2] | reserved0 | Reserved (2 bytes) |
| 4+ | ... | cfgData | Configuration data |

Extract EXACTLY what the PDF shows for this specific manual version.
Pay attention to whether offset 2 is "transaction" (U1) or "reserved0" (U1[2]).

Return using ubx_message_extraction tool.
""",

    "UBX-CFG-VALDEL": """You are extracting UBX-CFG-VALDEL from u-blox PDF manual pages.

This message structure varies by firmware version:

**Newer versions:**
| Offset | Type | Name | Description |
|--------|------|------|-------------|
| 0 | U1 | version | Message version |
| 1 | U1 | layers | Configuration layers to delete from |
| 2 | U1 | transaction | Transaction mode |
| 3 | U1 | reserved0 | Reserved |
| 4+ | ... | keys | Configuration keys to delete |

**Older versions:**
| Offset | Type | Name | Description |
|--------|------|------|-------------|
| 0 | U1 | version | Message version |
| 1 | U1 | layers | Configuration layers |
| 2 | U1[2] | reserved0 | Reserved (2 bytes) |
| 4+ | ... | keys | Configuration keys |

Extract EXACTLY what the PDF shows for this specific manual version.

Return using ubx_message_extraction tool.
""",

    "UBX-TIM-VCOCAL": """You are extracting UBX-TIM-VCOCAL from u-blox PDF manual pages.

This message has TWO completely different structures:

**UBX-TIM-VCOCAL-SET (Command, 1 byte):**
| Offset | Type | Name | Description |
|--------|------|------|-------------|
| 0 | U1 | type | VCOCAL command type |

**UBX-TIM-VCOCAL-GET (Response, 12 bytes):**
| Offset | Type | Name | Description |
|--------|------|------|-------------|
| 0 | U1 | type | VCOCAL type |
| 1 | U1 | version | Message version |
| 2 | U1 | oscId | Oscillator ID |
| 3 | U1 | reserved0 | Reserved |
| 4 | U2 | gainUncertainty | Gain uncertainty |
| 6 | I4 | gainVco | VCO gain |
| 10 | U1[2] | reserved1 | Reserved |

Extract based on message name suffix:
- "UBX-TIM-VCOCAL-SET" → SET structure (1 byte)
- "UBX-TIM-VCOCAL-GET" or "UBX-TIM-VCOCAL" → GET structure (12 bytes)

Do NOT merge both structures. Return using ubx_message_extraction tool.
""",

    "UBX-CFG-DAT": """You are extracting UBX-CFG-DAT from u-blox PDF manual pages.

This message has THREE different structures:

**UBX-CFG-DAT-POLL (Poll request, 0 bytes):**
Empty payload - just polls for current datum.

**UBX-CFG-DAT-SET (Set datum, 52 bytes):**
| Offset | Type | Name |
|--------|------|------|
| 0 | R8 | majA |
| 8 | R8 | flat |
| 16 | R4 | dX |
| 20 | R4 | dY |
| 24 | R4 | dZ |
| 28 | R4 | rotX |
| 32 | R4 | rotY |
| 36 | R4 | rotZ |
| 40 | R4 | scale |

**UBX-CFG-DAT-GET (Get datum response, 52 bytes):**
| Offset | Type | Name |
|--------|------|------|
| 0 | U2 | datumNum |
| 2 | CH[6] | datumName |
| 8 | R8 | majA |
| 16 | R8 | flat |
| 24 | R4 | dX |
| ... (continues with dY, dZ, rotX, rotY, rotZ, scale) |

Extract based on message name suffix:
- "UBX-CFG-DAT-POLL" → empty payload
- "UBX-CFG-DAT-SET" → SET structure (starts with majA)
- "UBX-CFG-DAT-GET" or "UBX-CFG-DAT" → GET structure (starts with datumNum)

Do NOT merge structures. Return using ubx_message_extraction tool.
""",

    "UBX-MON-GNSS": """You are extracting UBX-MON-GNSS from u-blox PDF manual pages.

This message has TWO different structures depending on receiver:

**UBX-MON-GNSS-V0 (Standard, 8 bytes):**
| Offset | Type | Name | Description |
|--------|------|------|-------------|
| 0 | U1 | version | Message version (0x00) |
| 1 | X1 | supported | Supported GNSS bitfield |
| 2 | X1 | defaultGnss | Default GNSS bitfield |
| 3 | X1 | enabled | Enabled GNSS bitfield |
| 4 | U1 | simultaneous | Max simultaneous GNSS |
| 5 | U1[3] | reserved0 | Reserved |

**UBX-MON-GNSS-V1 (X20 with signal plans, variable):**
| Offset | Type | Name | Description |
|--------|------|------|-------------|
| 0 | U1 | version | Message version (0x01) |
| 1 | U1 | numPlans | Number of signal plans |
| 2 | X2 | activePlanInfo | Active plan info bitfield |
| 4+ | ... | (repeated group) | Signal plan details |

Check for "numPlans" field to determine version:
- If field at offset 1 is "supported" (X1) → V0 (version=0x00)
- If field at offset 1 is "numPlans" (U1) → V1 (version=0x01)

IMPORTANT: Name the message based on which version the PDF documents:
- If 8 bytes with "supported" field: name = "UBX-MON-GNSS-V0"
- If variable with "numPlans" field: name = "UBX-MON-GNSS-V1"

Return using ubx_message_extraction tool.
""",

    "UBX-NAV-RELPOSNED": """You are extracting UBX-NAV-RELPOSNED from u-blox PDF manual pages.

This message has TWO different structures:

**UBX-NAV-RELPOSNED-V0 (40 bytes, M8/older):**
| Offset | Type | Name |
|--------|------|------|
| 0 | U1 | version (0x00) |
| 1 | U1 | reserved1 |
| 2 | U2 | refStationId |
| 4 | U4 | iTOW |
| 8 | I4 | relPosN |
| 12 | I4 | relPosE |
| 16 | I4 | relPosD |
| 20 | I1 | relPosHPN |
| 21 | I1 | relPosHPE |
| 22 | I1 | relPosHPD |
| 23 | U1 | reserved2 |
| 24 | U4 | accN |
| 28 | U4 | accE |
| 32 | U4 | accD |
| 36 | X4 | flags |

**UBX-NAV-RELPOSNED-V1 (64 bytes, F9/newer):**
| Offset | Type | Name |
|--------|------|------|
| 0 | U1 | version (0x01) |
| 1 | U1 | reserved0 |
| 2 | U2 | refStationId |
| 4 | U4 | iTOW |
| 8 | I4 | relPosN |
| 12 | I4 | relPosE |
| 16 | I4 | relPosD |
| 20 | I4 | relPosLength |
| 24 | I4 | relPosHeading |
| 28 | U4 | reserved1 |
| 32 | I1 | relPosHPN |
| 33 | I1 | relPosHPE |
| 34 | I1 | relPosHPD |
| 35 | I1 | relPosHPLength |
| 36 | U4 | accN |
| 40 | U4 | accE |
| 44 | U4 | accD |
| 48 | U4 | accLength |
| 52 | U4 | accHeading |
| 56 | U4 | reserved2 |
| 60 | X4 | flags |

Check payload length: 40 bytes = V0, 64 bytes = V1.

IMPORTANT: Name the message based on which version the PDF documents:
- If payload is 40 bytes: name = "UBX-NAV-RELPOSNED-V0"
- If payload is 64 bytes: name = "UBX-NAV-RELPOSNED-V1"

Return using ubx_message_extraction tool.
""",

    # UBX-RXM-MEASX - Complex message with multiple TOW fields
    "UBX-RXM-MEASX": """You are extracting UBX-RXM-MEASX from u-blox PDF manual pages.

This message has a FIXED header followed by a repeated satellite block.

**CRITICAL: Extract ALL these header fields (offsets 0-43):**

| Offset | Type | Name | Description |
|--------|------|------|-------------|
| 0 | U1 | version | Message version |
| 1 | U1[3] | reserved0 | Reserved |
| 4 | U4 | gpsTOW | GPS TOW (ms) |
| 8 | U4 | gloTOW | GLONASS TOW (ms) |
| 12 | U4 | bdsTOW | BeiDou TOW (ms) |
| 16 | U1[4] | reserved1 | Reserved |
| 20 | U4 | qzssTOW | QZSS TOW (ms) |
| 24 | U2 | gpsTOWAcc | GPS TOW accuracy |
| 26 | U2 | gloTOWAcc | GLONASS TOW accuracy |
| 28 | U2 | bdsTOWAcc | BeiDou TOW accuracy |
| 30 | U1[2] | reserved2 | Reserved |
| 32 | U2 | qzssTOWAcc | QZSS TOW accuracy |
| 34 | U1 | numSV | Number of satellites |
| 35 | X1 | flags | Flags bitfield |
| 36 | U1[8] | reserved3 | Reserved |

**IMPORTANT**: The TOW accuracy fields (gpsTOWAcc, gloTOWAcc, bdsTOWAcc, qzssTOWAcc) are U2 types at offsets 24, 26, 28, 32. Do NOT omit these fields.

The repeated satellite block starts at offset 44 with 24 bytes per satellite.

Return using ubx_message_extraction tool.
""",

    # UBX-MON-TXBUF - Array fields for each target
    "UBX-MON-TXBUF": """You are extracting UBX-MON-TXBUF from u-blox PDF manual pages.

This message has ARRAY fields for 6 targets (DDC, UART1, UART2, USB, SPI, reserved).

**CRITICAL: These fields are ARRAYS, not single values:**

| Offset | Type | Name | Description |
|--------|------|------|-------------|
| 0 | U2[6] | pending | Bytes pending per target (6 x U2 = 12 bytes) |
| 12 | U1[6] | usage | Buffer usage % per target (6 x U1 = 6 bytes) |
| 18 | U1[6] | peakUsage | Peak buffer usage % per target (6 x U1 = 6 bytes) |
| 24 | U1 | tUsage | Total buffer usage % |
| 25 | U1 | tPeakusage | Total peak buffer usage % |
| 26 | X1 | errors | Error bitmask |
| 27 | U1 | reserved0 | Reserved |

**IMPORTANT**: 
- `pending` is U2[6] (array of 6 U2 values), NOT a single U2
- `usage` is U1[6] (array of 6 U1 values), NOT a single U1
- `peakUsage` is U1[6] (array of 6 U1 values), NOT a single U1

Total payload length: 28 bytes.

Return using ubx_message_extraction tool.
""",

    # UBX-INF-NOTICE - Variable length string message
    "UBX-INF-NOTICE": """You are extracting UBX-INF-NOTICE from u-blox PDF manual pages.

This is an informational message containing a variable-length ASCII string.

**Message structure:**

| Offset | Type | Name | Description |
|--------|------|------|-------------|
| 0 | CH | str | ASCII character (repeated to fill payload) |

**IMPORTANT**: 
- The payload is a variable-length ASCII string
- Extract the `str` field as type CH
- The message has variable length (0 + N*1 bytes)

Return using ubx_message_extraction tool.
""",

    # UBX-INF-TEST - Same structure as INF-NOTICE
    "UBX-INF-TEST": """You are extracting UBX-INF-TEST from u-blox PDF manual pages.

This is an informational message containing a variable-length ASCII string.

**Message structure:**

| Offset | Type | Name | Description |
|--------|------|------|-------------|
| 0 | CH | str | ASCII character (repeated to fill payload) |

**IMPORTANT**: 
- The payload is a variable-length ASCII string
- Extract the `str` field as type CH
- The message has variable length (0 + N*1 bytes)

Return using ubx_message_extraction tool.
""",

    # UBX-CFG-NMEA - CH fields are single characters, not arrays
    "UBX-CFG-NMEA": """You are extracting UBX-CFG-NMEA from u-blox PDF manual pages.

**CRITICAL for talker ID fields:**
- `bdsTalkerId` is type CH (single character), NOT CH[2]
- `gpsTalkerId` is type CH (single character), NOT CH[2]

The CH type in UBX represents a single ASCII character (1 byte).
When the manual shows "2 bytes" for a talker ID, it means 2 separate CH fields, not an array.

Return using ubx_message_extraction tool.
""",
}

# Messages known to have array extraction issues
ARRAY_PROBLEM_MESSAGES = {
    "UBX-CFG-NAVX5", "UBX-CFG-NMEA", "UBX-CFG-PRT", "UBX-CFG-VALSET",
    "UBX-MGA-DBD", "UBX-MGA-GAL", "UBX-MGA-GPS-EPH", "UBX-MON-COMMS",
    "UBX-MON-MSGPP", "UBX-MON-RF", "UBX-MON-SPAN", "UBX-MON-TXBUF",
    "UBX-NAV-ORB", "UBX-NAV-PVT", "UBX-NAV-SIG", "UBX-RXM-COR",
    "UBX-RXM-SPARTN", "UBX-SEC-OSNMA", "UBX-SEC-SIG",
}

# Messages known to have bitfield type issues
BITFIELD_PROBLEM_MESSAGES = {
    "UBX-CFG-ODO", "UBX-RXM-MEASX", "UBX-RXM-PMREQ", "UBX-MGA-INI",
}


def build_extraction_prompt(
    message_name: str,
    expected_class_id: str | None = None,
    expected_message_id: str | None = None,
) -> str:
    """Build an extraction prompt tailored to the specific message.
    
    Args:
        message_name: Full message name (e.g., "UBX-NAV-PVT")
        expected_class_id: Expected class ID from TOC
        expected_message_id: Expected message ID from TOC
    
    Returns:
        Tailored extraction prompt
    """
    # Check for dedicated prompt first (complete replacement)
    for dedicated_base, dedicated_prompt in DEDICATED_PROMPTS.items():
        if message_name.startswith(dedicated_base):
            return dedicated_prompt
    
    # Otherwise, build modular prompt
    anchor = ""
    if expected_class_id and expected_message_id:
        anchor = f"\nExpected IDs: class_id={expected_class_id}, message_id={expected_message_id}"
    
    # Start with base prompt
    prompt = BASE_PROMPT.format(
        message_name=message_name,
        anchor=anchor,
    )
    
    # Get base name without variant suffix for matching
    parts = message_name.split("-")
    base_name = "-".join(parts[0:3]) if len(parts) >= 3 else message_name
    
    # Add array guidance if this message has known array issues
    if base_name in ARRAY_PROBLEM_MESSAGES or message_name in ARRAY_PROBLEM_MESSAGES:
        prompt += ARRAY_GUIDANCE
    
    # Add bitfield guidance if this message has known bitfield issues
    if base_name in BITFIELD_PROBLEM_MESSAGES or message_name in BITFIELD_PROBLEM_MESSAGES:
        prompt += BITFIELD_GUIDANCE
    
    # Add variant-specific guidance (short additions, not full replacement)
    for variant_base, guidance in VARIANT_GUIDANCE.items():
        if message_name.startswith(variant_base):
            prompt += guidance
            break
    
    # Add enum guidance if relevant enum fields exist
    enum_hints = get_enum_hints_for_message(message_name)
    if enum_hints:
        prompt += ENUM_GUIDANCE.format(enum_hints=enum_hints)
    
    prompt += "\n\nReturn the extracted message using the ubx_message_extraction tool."
    
    return prompt


@lru_cache(maxsize=1)
def load_enumerations() -> dict:
    """Load canonical enumeration definitions from data/enumerations.json."""
    enum_file = Path(__file__).parent.parent.parent / "data" / "enumerations.json"
    if enum_file.exists():
        with open(enum_file) as f:
            return json.load(f)
    return {}


def get_enum_hints_for_message(message_name: str) -> str:
    """Get formatted enum hints for fields that might appear in a message.
    
    Returns formatted string of enum hints, or empty string if none relevant.
    """
    enums = load_enumerations()
    if not enums:
        return ""
    
    # Map message prefixes to likely enum fields
    message_enum_fields = {
        "UBX-NAV-PVT": ["fixType", "gnssId"],
        "UBX-NAV-PVAT": ["fixType"],
        "UBX-LOG-BATCH": ["fixType"],
        "UBX-LOG-RETRIEVEPOS": ["fixType"],
        "UBX-CFG-NAV5": ["dynModel", "fixMode", "utcStandard"],
        "UBX-CFG-NMEA": ["nmeaVersion", "numSV", "svNumbering", "mainTalkerId", "gsvTalkerId"],
        "UBX-CFG-GEOFENCE": ["pioEnabled", "pinPolarity"],
        "UBX-CFG-PMS": ["powerSetupValue"],
        "UBX-CFG-RATE": ["timeRef"],
        "UBX-CFG-RST": ["resetMode"],
        "UBX-CFG-RXM": ["lpMode"],
        "UBX-CFG-TP5": ["tpIdx"],
        "UBX-CFG-DAT": ["datumNum"],
        "UBX-MGA-ACK": ["ackType", "infoCode"],
        "UBX-MGA-INI-TIME-GNSS": ["gnssId"],
        "UBX-MON-HW": ["aStatus", "aPower"],
        "UBX-MON-HW2": ["cfgSource"],
        "UBX-NAV-TIMELS": ["lsChange"],
    }
    
    # Find matching fields for this message
    relevant_fields = []
    for msg_prefix, fields in message_enum_fields.items():
        if message_name.startswith(msg_prefix):
            relevant_fields.extend(fields)
    
    if not relevant_fields:
        return ""
    
    # Format hints for relevant fields
    hints = []
    for field_name in relevant_fields:
        if field_name in enums:
            enum_data = enums[field_name]
            values_str = ", ".join(
                f"{v['value']}={v['name']}" 
                for v in enum_data.get("values", [])[:8]  # Limit to 8 values
            )
            if len(enum_data.get("values", [])) > 8:
                values_str += ", ..."
            hints.append(f"- {field_name}: {values_str}")
    
    return "\n".join(hints)


def get_prompt_type(message_name: str) -> str:
    """Get the type of prompt that will be used for a message.
    
    Returns:
        'dedicated' if a dedicated prompt exists
        'base+array' if array guidance will be added
        'base+bitfield' if bitfield guidance will be added
        'base+variant' if variant guidance will be added
        'base' for standard base prompt
    """
    for dedicated_base in DEDICATED_PROMPTS:
        if message_name.startswith(dedicated_base):
            return 'dedicated'
    
    parts = message_name.split("-")
    base_name = "-".join(parts[0:3]) if len(parts) >= 3 else message_name
    
    additions = []
    if base_name in ARRAY_PROBLEM_MESSAGES or message_name in ARRAY_PROBLEM_MESSAGES:
        additions.append('array')
    if base_name in BITFIELD_PROBLEM_MESSAGES or message_name in BITFIELD_PROBLEM_MESSAGES:
        additions.append('bitfield')
    for variant_base in VARIANT_GUIDANCE:
        if message_name.startswith(variant_base):
            additions.append('variant')
            break
    
    if additions:
        return 'base+' + '+'.join(additions)
    return 'base'
