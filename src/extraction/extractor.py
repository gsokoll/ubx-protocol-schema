"""Claude-based UBX message extraction from PDF pages.

This module provides the core extraction logic using Anthropic's Claude API
to parse PDF page images into structured UBX message definitions.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic

PROMPT_VERSION = "1.6"  # Use modular prompts from src/extraction/prompts.py

# Import modular prompts - fall back to legacy if not available
try:
    from src.extraction.prompts import build_extraction_prompt as build_modular_prompt
    USE_MODULAR_PROMPTS = True
except ImportError:
    USE_MODULAR_PROMPTS = False

SCALAR_DATA_TYPES = ["U1", "I1", "X1", "U2", "I2", "X2", "U4", "I4", "X4", "R4", "R8", "I8", "CH", "RU1_3", "RU2_5"]
ARRAY_BASE_TYPES = ["U1", "I1", "X1", "U2", "I2", "X2", "U4", "I4", "X4", "R4", "R8", "I8", "CH"]
MESSAGE_TYPES = [
    "input", "output", "command", "set", "get", "get_set",
    "poll_request", "polled", "periodic", "periodic_polled", "input_output"
]


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass
class ExtractionResult:
    message_name: str
    success: bool
    message: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    cache_key: str = ""
    usage: TokenUsage | None = None


def _build_extraction_tool_schema() -> dict[str, Any]:
    """Build the tool schema for message extraction, matching ubx-message-schema-v1.1.json."""
    return {
        "name": "ubx_message_extraction",
        "description": "Extract a single UBX message definition from PDF page images into structured JSON.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Full message name (e.g., 'UBX-NAV-PVT')"
                },
                "class_id": {
                    "type": "string",
                    "pattern": "^0x[0-9a-fA-F]{2}$",
                    "description": "Class ID as hex (e.g., '0x01')"
                },
                "message_id": {
                    "type": "string",
                    "pattern": "^0x[0-9a-fA-F]{2}$",
                    "description": "Message ID as hex (e.g., '0x07')"
                },
                "description": {
                    "type": "string",
                    "description": "Short description of the message from the PDF"
                },
                "message_type": {
                    "type": "string",
                    "enum": MESSAGE_TYPES,
                    "description": "Direction and nature of the message"
                },
                "payload": {
                    "type": "object",
                    "properties": {
                        "length": {
                            "type": "object",
                            "description": "Payload length specification",
                            "properties": {
                                "fixed": {"type": "integer"},
                                "variable": {
                                    "type": "object",
                                    "properties": {
                                        "base": {"type": "integer"},
                                        "formula": {"type": "string"},
                                        "min": {"type": "integer"},
                                        "max": {"type": ["integer", "null"]}
                                    }
                                }
                            }
                        },
                        "fields": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "byte_offset": {"type": "integer"},
                                    "data_type": {
                                        "oneOf": [
                                            {"type": "string", "enum": SCALAR_DATA_TYPES},
                                            {
                                                "type": "object",
                                                "properties": {
                                                    "array_of": {"type": "string", "enum": ARRAY_BASE_TYPES},
                                                    "count": {"type": "integer"}
                                                },
                                                "required": ["array_of", "count"]
                                            }
                                        ]
                                    },
                                    "description": {"type": "string"},
                                    "unit": {"type": "string"},
                                    "scale": {
                                        "type": "object",
                                        "properties": {
                                            "raw": {"type": "string"},
                                            "multiplier": {"type": "number"}
                                        },
                                        "required": ["raw", "multiplier"]
                                    },
                                    "reserved": {"type": "boolean"},
                                    "bitfield": {
                                        "type": "object",
                                        "properties": {
                                            "bits": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "name": {"type": "string"},
                                                        "bit_start": {"type": "integer"},
                                                        "bit_end": {"type": "integer"},
                                                        "data_type": {"type": "string", "enum": ["U", "I", "S"]},
                                                        "description": {"type": "string"},
                                                        "reserved": {"type": "boolean"}
                                                    },
                                                    "required": ["name", "bit_start", "bit_end", "data_type"]
                                                }
                                            }
                                        },
                                        "required": ["bits"]
                                    }
                                },
                                "required": ["name", "byte_offset", "data_type"]
                            }
                        },
                        "repeated_groups": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "repetition_type": {
                                        "type": "string",
                                        "enum": ["count_field", "constant", "optional", "fill_remaining"]
                                    },
                                    "count_field": {"type": "string"},
                                    "constant_count": {"type": "integer"},
                                    "group_size_bytes": {"type": "integer"},
                                    "base_offset": {"type": "integer"},
                                    "fields": {"type": "array"}
                                },
                                "required": ["name", "repetition_type", "group_size_bytes", "base_offset", "fields"]
                            }
                        }
                    },
                    "required": ["length", "fields"]
                }
            },
            "required": ["name", "class_id", "message_id", "message_type", "payload"],
            "additionalProperties": False
        }
    }


def _build_extraction_prompt(
    *,
    message_name: str,
    expected_class_id: str | None,
    expected_message_id: str | None,
) -> str:
    """Build the extraction prompt with mitigations for known issues."""
    
    anchor = ""
    if expected_class_id and expected_message_id:
        anchor = f"\nExpected IDs from TOC: class_id={expected_class_id}, message_id={expected_message_id}"
    
    return f"""You are extracting a UBX protocol message definition from u-blox PDF manual pages.

TARGET MESSAGE: {message_name}{anchor}

CRITICAL INSTRUCTIONS:
1. Extract ONLY the message named "{message_name}". Ignore any other messages visible on these pages.
2. If you see partial content from adjacent messages (before/after), do NOT include their fields.
3. The payload table shows fields in order. Extract them exactly as shown with correct byte offsets.
4. For X-type fields (X1, X2, X4), extract the bitfield structure if a sub-table is shown.

FIELD EXTRACTION RULES:
- byte_offset: The exact byte offset from the "Offset" column (integer, 0-indexed)
- data_type: Use exact UBX types: U1, I1, X1, U2, I2, X2, U4, I4, X4, R4, R8, I8, CH
- For arrays: use {{"array_of": "U1", "count": N}} format
- scale: If a scaling factor is shown (e.g., "1e-7", "2^-5"), include both "raw" string and numeric "multiplier"
- unit: Physical unit if shown (e.g., "ms", "deg", "m/s")
- reserved: Set to true for reserved fields (often named "reserved" or shown as "-")
- bitfield: For X-type fields with bit definitions, extract each bit/bit-range

ARRAY DETECTION (CRITICAL - common extraction error):
- Check the "Type" column carefully: "U1[6]" or "U1 x 6" means {{"array_of": "U1", "count": 6}}
- Check the field size: if offset jumps by more than the base type size, it's an array
  Example: reserved0 at offset 4, next field at offset 8 with type U1 = {{"array_of": "U1", "count": 4}}
- Reserved fields often span multiple bytes - ALWAYS verify the size from offset differences
- String fields (CH type) are usually arrays: {{"array_of": "CH", "count": N}} or "variable"

BITFIELD TYPE DETECTION (CRITICAL - common extraction error):
- Use X1/X2/X4 (NOT U1/U2/U4) when:
  - The field is named "flags", "mask", "status", "cfg", "supported", "enabled"
  - The description mentions "bitfield" or lists individual bit meanings
  - There's a sub-table showing bit positions and their meanings
- U types are for numeric values, X types are for bitfields/flags

PAYLOAD LENGTH:
- If fixed length shown (e.g., "28 bytes"), use {{"fixed": 28}}
- If variable (e.g., "8 + N*12"), use {{"variable": {{"base": 8, "formula": "8 + N*12"}}}}

MESSAGE TYPE DETERMINATION:
- "periodic" or "periodic_polled": Output messages sent automatically or on poll
- "input": Messages sent TO the receiver
- "output": Messages sent FROM the receiver
- "command": One-shot commands
- "get"/"set"/"get_set": Configuration messages

QUALITY CHECKS (verify before returning):
- Byte offsets should be sequential and non-overlapping (except for bitfields within same byte)
- Total of field sizes should match payload length
- Field names should match exactly what's in the PDF table

SPECIAL MESSAGE TYPES:

UBX-INF-* (Information messages like UBX-INF-DEBUG, UBX-INF-ERROR, UBX-INF-NOTICE, UBX-INF-WARNING, UBX-INF-TEST):
- These messages contain a variable-length ASCII string payload
- ALWAYS extract a single field named "str" with data_type "CH" or {{"array_of": "CH", "count": "variable"}}
- The payload length is variable, use {{"variable": {{"base": 0, "formula": "0 + N*1", "min": 0}}}}
- Do NOT return an empty fields array for these messages

UBX-MGA-* (Multiple GNSS Assistance messages):
- These messages often have MULTIPLE SUB-TYPES documented on the same pages (e.g., MGA-GPS-EPH, MGA-GPS-ALM, MGA-GPS-IONO)
- Each sub-type has a different "type" field value and different payload structure
- Extract ONLY ONE sub-type per extraction - prefer the FIRST/PRIMARY one shown (usually EPH for ephemeris)
- Include the "type" field which indicates the sub-type (e.g., type=1 for EPH, type=2 for ALM)
- If the message name includes the sub-type (e.g., "UBX-MGA-GPS-EPH"), extract only that specific sub-type

UBX-LOG-FINDTIME (Request/Response message):
- This message has TWO DIFFERENT PAYLOAD STRUCTURES - one for INPUT (request) and one for OUTPUT (response)
- INPUT (request): version, type, year, month, day, hour, minute, second, reserved - used to find a log entry by time
- OUTPUT (response): version, type, reserved, entryNumber - returns the matching log entry number
- If extracting "UBX-LOG-FINDTIME-INPUT" or just "UBX-LOG-FINDTIME", extract the INPUT structure with year/month/day/hour/minute/second fields
- If extracting "UBX-LOG-FINDTIME-OUTPUT", extract the OUTPUT structure with entryNumber field
- Set message_type to "input" for request, "output" for response
- Do NOT merge both structures into one message

UBX-RXM-RLM (Galileo SAR Return Link Message - Short/Long variants):
- This message has TWO DIFFERENT PAYLOAD STRUCTURES based on the "type" field value
- SHORT-RLM (type=0x01, 16 bytes): version, type, svId, reserved0, beacon[8], message, params[2], reserved1
- LONG-RLM (type=0x02, 28 bytes): version, type, svId, reserved0, beacon[8], message, params[12]
- If extracting "UBX-RXM-RLM-SHORT" or just "UBX-RXM-RLM", extract the SHORT structure (16 bytes)
- If extracting "UBX-RXM-RLM-LONG", extract the LONG structure (28 bytes)
- The "type" field at offset 1 indicates which variant: 0x01=short, 0x02=long
- Do NOT merge both structures into one message

UBX-RXM-PMREQ (Power Management Request - V0/V1 variants):
- This message has TWO DIFFERENT PAYLOAD STRUCTURES based on firmware version
- V0 (8 bytes, older): duration (U4), flags (X4) - NO version field
- V1 (16 bytes, newer): version (U1), reserved0[3], duration (U4), flags (X4), wakeupSources (X4)
- If extracting "UBX-RXM-PMREQ-V0", extract the 8-byte structure starting with duration
- If extracting "UBX-RXM-PMREQ-V1", extract the 16-byte structure starting with version
- If just "UBX-RXM-PMREQ", check payload length: 8 bytes = V0, 16 bytes = V1
- Do NOT merge both structures into one message

UBX-CFG-VALSET/VALDEL (Configuration messages with version differences):
- Older versions have "transaction" field at offset 2 (U1)
- Newer versions have "reserved0" at offset 2 (U1[2])
- Extract exactly what the PDF shows for the specific manual version

BITFIELD EXTRACTION (CRITICAL):
- For ANY field with data_type X1, X2, or X4, you MUST extract the bitfield structure
- Look for sub-tables or descriptions showing individual bit meanings
- Common bitfield fields: flags, mask, status, cfg, supported, enabled
- Example fields that MUST have bitfields: loadMask, saveMask, deviceMask, flags, supported, pinMask
- Each bit should have: name, bit_position (or bit_range for multi-bit fields), description

UNIT EXTRACTION (CRITICAL):
- ALWAYS capture units when shown in the PDF (e.g., "ms", "deg", "m/s", "%", "C")
- Units are often in parentheses or a separate "Unit" column
- Common units: ms, s, deg, m, m/s, mm, cm, %, Hz, dBHz, C (Celsius)
- If a field shows a unit like "%" for percentage, include unit: "%"

FIELD NAME CONSISTENCY:
- Use exact field names as shown in the PDF table
- Preserve camelCase as shown (e.g., "cpuLoad" not "cpuload")
- For repeated/array fields, include all fields from the repeated block

Return the extracted message using the ubx_message_extraction tool."""


def compute_cache_key(
    *,
    pdf_path: str,
    message_name: str,
    page_hashes: list[str],
    model: str,
) -> str:
    """Compute a deterministic cache key for extraction results."""
    key_data = {
        "pdf": pdf_path,
        "message": message_name,
        "pages": sorted(page_hashes),
        "model": model,
        "prompt_version": PROMPT_VERSION,
    }
    key_str = json.dumps(key_data, sort_keys=True)
    return hashlib.sha256(key_str.encode()).hexdigest()[:16]


def hash_image(img_bytes: bytes) -> str:
    """Hash image bytes for cache key computation."""
    return hashlib.sha256(img_bytes).hexdigest()[:12]


def call_claude_for_extraction(
    *,
    images: list[bytes],
    message_name: str,
    expected_class_id: str | None,
    expected_message_id: str | None,
    model: str,
    max_tokens: int = 8192,
    additional_context: str | None = None,
) -> tuple[dict[str, Any], TokenUsage]:
    """Call Claude API to extract a message definition from PDF page images.
    
    Args:
        additional_context: Optional context to prepend to the prompt (e.g., error
            context for re-extraction attempts).
    """
    client = anthropic.Anthropic()

    content: list[dict[str, Any]] = []
    for img_bytes in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(img_bytes).decode("utf-8"),
            },
        })

    # Use modular prompts if available, otherwise fall back to legacy
    if USE_MODULAR_PROMPTS:
        prompt = build_modular_prompt(
            message_name=message_name,
            expected_class_id=expected_class_id,
            expected_message_id=expected_message_id,
        )
    else:
        prompt = _build_extraction_prompt(
            message_name=message_name,
            expected_class_id=expected_class_id,
            expected_message_id=expected_message_id,
        )
    
    # Prepend additional context if provided (e.g., re-extraction error context)
    if additional_context:
        prompt = additional_context + "\n\n" + prompt
    
    content.append({"type": "text", "text": prompt})

    tool = _build_extraction_tool_schema()

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
    )

    usage = TokenUsage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
    )

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool["name"]:
            return block.input, usage

    text = ""
    if response.content and getattr(response.content[0], "type", None) == "text":
        text = response.content[0].text

    return {"error": "Claude response did not contain expected tool output", "raw": text}, usage


def validate_extraction(result: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """Validate extracted message against schema requirements and sanity checks."""
    errors: list[str] = []
    warnings: list[str] = []

    if "error" in result:
        errors.append(str(result["error"]))
        return False, errors, warnings

    required_fields = ["name", "class_id", "message_id", "message_type", "payload"]
    for f in required_fields:
        if f not in result:
            errors.append(f"Missing required field: {f}")

    if errors:
        return False, errors, warnings

    payload = result.get("payload", {})
    if not isinstance(payload, dict):
        errors.append(f"payload should be dict, got {type(payload).__name__}")
        return False, errors, warnings
    fields = payload.get("fields", [])

    if not fields:
        warnings.append("No fields extracted")

    prev_offset = -1
    for i, fld in enumerate(fields):
        offset = fld.get("byte_offset")
        if offset is None:
            errors.append(f"Field {i} ({fld.get('name', '?')}) missing byte_offset")
            continue

        if isinstance(offset, int):
            if offset < prev_offset and not fld.get("reserved"):
                warnings.append(f"Field {i} ({fld.get('name')}) offset {offset} < previous {prev_offset}")
            prev_offset = max(prev_offset, offset)

        if "data_type" not in fld:
            errors.append(f"Field {i} ({fld.get('name', '?')}) missing data_type")

    length_spec = payload.get("length", {})
    if not length_spec:
        warnings.append("No payload length specified")
    elif "fixed" in length_spec:
        fixed_len = length_spec["fixed"]
        if fields:
            last_field = fields[-1]
            last_offset = last_field.get("byte_offset", 0)
            dt = last_field.get("data_type")
            if isinstance(dt, str):
                type_sizes = {"U1": 1, "I1": 1, "X1": 1, "U2": 2, "I2": 2, "X2": 2,
                              "U4": 4, "I4": 4, "X4": 4, "R4": 4, "R8": 8, "I8": 8, "CH": 1}
                size = type_sizes.get(dt, 1)
                expected_end = last_offset + size
                if expected_end != fixed_len:
                    warnings.append(f"Last field ends at {expected_end} but payload length is {fixed_len}")

    class_id = result.get("class_id", "")
    msg_id = result.get("message_id", "")
    if class_id and not class_id.startswith("0x"):
        errors.append(f"class_id '{class_id}' should be hex format (0xNN)")
    if msg_id and not msg_id.startswith("0x"):
        errors.append(f"message_id '{msg_id}' should be hex format (0xNN)")

    return len(errors) == 0, errors, warnings


def normalize_extraction(result: dict[str, Any], message_name: str, cache_key: str = "") -> ExtractionResult:
    """Normalize Claude's extraction output into an ExtractionResult."""
    if "error" in result:
        return ExtractionResult(
            message_name=message_name,
            success=False,
            errors=[str(result.get("error"))],
            raw=result,
            cache_key=cache_key,
        )

    valid, errors, warnings = validate_extraction(result)

    return ExtractionResult(
        message_name=result.get("name", message_name),
        success=valid,
        message=result if valid else None,
        errors=errors,
        warnings=warnings,
        raw=result,
        cache_key=cache_key,
    )
