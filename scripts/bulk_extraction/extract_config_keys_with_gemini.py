#!/usr/bin/env python3
"""Extract configuration keys from u-blox PDFs using Google Gemini API.

Single API call approach: Uploads entire config section (intro + reference) as one PDF.

Pricing (per 1M tokens):
    - Gemini 2.5 Flash-Lite: $0.10 input / $0.40 output
    - Claude Sonnet 4: $3.00 input / $15.00 output
    => Gemini is ~30x cheaper

Usage:
    export GOOGLE_API_KEY="your-api-key"
    uv run python scripts/extract_config_keys_with_gemini.py --pdf-path <path>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

GEMINI_MODELS = {
    "flash-lite": "gemini-2.5-flash-lite",
    "flash": "gemini-2.5-flash",
    "pro": "gemini-2.5-pro",
}

PRICING = {
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
}

# Prompt for batch extraction (intro pages + multiple groups)
GEMINI_BATCH_PROMPT = """You are extracting UBX configuration key definitions from a u-blox interface description PDF.

This PDF contains:
1. INTRO PAGES: Configuration interface introduction (data types, layers, transactions, etc.)
2. GROUP PAGES: Configuration keys for these SPECIFIC groups: {group_list}

IMPORTANT: Only extract keys from the groups listed above. The pages may contain partial content from other groups at boundaries - ignore those.

DATA TYPES (use EXACTLY these values for data_type field):
- L = Boolean (1 bit)
- U1, U2, U4, U8 = Unsigned integers (1/2/4/8 bytes)
- I1, I2, I4, I8 = Signed integers (1/2/4/8 bytes) - NOTE: "I" is capital letter i, NOT digit 1
- X1, X2, X4, X8 = Bitfields (extract bit definitions)
- E1, E2, E4 = Enumerations (extract constant tables)
- R4, R8 = Floating point (4/8 bytes)

=== CHARACTER RECOGNITION WARNINGS ===

The PDF uses a sans-serif font with confusable characters:
- "I" (letter i) vs "1" (digit one): Data types are I1, I2, I4, I8 (not 11, 12, 14, 18)
- "O" (letter o) vs "0" (digit zero): Key names like CFG-ODO use letter "O" (not CFG-0D0)
- Key names like CFG-I2C use letter "I" (not CFG-12C)

IMPORTANT: Use only ASCII characters (A-Z, 0-9, hyphen, underscore) for key names.
Do NOT use Greek letters (Α, Ε, Μ, etc.) or Cyrillic letters that look similar to Latin letters.

=== KEY NAME FORMATTING ===

Key names use UNDERSCORES, never spaces. Examples:
- CORRECT: CFG-TMODE-HEIGHT_HP
- WRONG: CFG-TMODE-HEIGHT HP
If you see what looks like a space in a key name, it should be an underscore.

=== NAV vs NAV2 MESSAGE OUTPUT KEYS ===

CRITICAL: The CFG-MSGOUT group contains BOTH "NAV" and "NAV2" message keys.
These are DIFFERENT keys with DIFFERENT key_ids:
- CFG-MSGOUT-UBX_NAV_TIMELS_I2C (one key_id) - outputs UBX-NAV-TIMELS message
- CFG-MSGOUT-UBX_NAV2_TIMELS_I2C (different key_id) - outputs UBX-NAV2-TIMELS message

Do NOT confuse these. Each key_id is UNIQUE and maps to exactly ONE key name.
When extracting, ensure the name you record comes from the SAME table row as the key_id.

=== TABLE STRUCTURE WARNING ===

Configuration tables USUALLY have columns: Name | Key ID | Type | Scale | Unit | Description
HOWEVER, some older manuals (M9-SPG, M9-MDR, X20-HPG) may omit the Scale column entirely.

HOW TO DETECT: If the column that should be "Scale" contains unit abbreviations like
"m", "s", "Hz", "deg", "arcsec", "ppm" instead of numeric values, the table has NO Scale column.
In this case, what looks like Scale is actually Unit, and what looks like Unit is Description.

=== SCALE FIELD RULES ===

Scale MUST be a NUMERIC multiplier. Valid scale values:
- "1e-7", "1e-9", "0.01", "0.001", "0.0001", "1e-6"
- "-" (dash) means no scaling - OMIT the scale field entirely

Scale is NEVER a unit abbreviation. These are WRONG for scale:
- WRONG: "m", "s", "Hz", "deg", "arcsec", "ppm", "%" 
- If you see these in a "Scale" column, it's actually the Unit column (table has no Scale)

=== UNIT FIELD RULES ===

Unit is a SHORT physical unit abbreviation (typically 1-5 characters):
- Valid: "m", "s", "Hz", "deg", "%", "ms", "us", "km", "cm", "dBHz", "m/s", "arcsec", "ppm"
- "-" (dash) means dimensionless - OMIT the unit field entirely

Unit is NEVER a description or sentence. If you're about to write more than ~10 characters
in the unit field, STOP - you're probably reading the Description column by mistake.

=== EXAMPLES ===

Correct extraction from a 6-column table (Name|KeyID|Type|Scale|Unit|Desc):
- Scale="-", Unit="m" → omit scale, set unit="m"
- Scale="1e-7", Unit="deg" → set scale="1e-7", unit="deg"  
- Scale="-", Unit="-" → omit both scale and unit

Correct extraction from a 5-column table (Name|KeyID|Type|Unit|Desc) - NO Scale column:
- If you see Unit="m" and Description="Geodetic datum..." → set unit="m", omit scale

=== REQUIRED JSON OUTPUT ===
{{
  "keys": [
    {{
      "name": "CFG-GROUP-ITEM",
      "key_id": "0xNNNNNNNN",
      "data_type": "E1",
      "description": "Description text",
      "scale": "1e-7",
      "unit": "deg",
      "inline_enum": {{
        "values": {{
          "CONSTANT_NAME": {{"value": 0, "description": "Meaning"}}
        }}
      }},
      "bitfield": {{
        "bits": [
          {{"name": "bitName", "bit_start": 0, "bit_end": 0, "description": "Bit meaning"}}
        ]
      }}
    }}
  ]
}}

=== CRITICAL RULES ===
1. Each key_id is UNIQUE - ensure name and key_id come from the SAME row
2. Use EXACT field names: "name", "key_id", "data_type", "inline_enum", "bitfield"
3. Key names use UNDERSCORES, not spaces
4. For E-type keys: Extract ALL constants from "Constants for CFG-XXX-YYY" tables
5. For X-type keys: Extract ALL bit definitions from bit tables
6. Omit scale field if PDF shows "-"; omit unit field if PDF shows "-"
7. Only extract keys from: {group_list}

Return JSON with ALL keys from the specified groups, including complete enum/bitfield data.
"""

# Single prompt for extracting ALL config keys from entire section (legacy)
GEMINI_PROMPT = """You are extracting ALL UBX configuration key definitions from a u-blox interface description PDF.

DOCUMENT STRUCTURE:
This PDF contains the complete "Configuration interface" section:
- Section 6.1-6.8: Introduction (database, items, layers, data types, transactions, reset behavior, overview)
- Section 6.9: Configuration reference with ALL config key groups (CFG-BDS, CFG-GAL, CFG-RATE, etc.)

YOUR TASK:
Extract EVERY configuration key from ALL groups in section 6.9.

Each group has a table titled "Table N: CFG-XXX configuration items" with columns:
- Configuration item: Full key name (e.g., CFG-RATE-MEAS)
- Key ID: 32-bit hex (0xNNNNNNNN)
- Type: Data type
- Scale: Scaling factor or "-"
- Unit: Physical unit or "-"  
- Description: What the key does

DATA TYPES (from section 6.5):
- L = Boolean (1 bit)
- U1/U2/U4/U8 = Unsigned integers
- I1/I2/I4/I8 = Signed integers
- X1/X2/X4 = Bitfields (extract bit definitions if shown)
- E1/E2/E4 = Enumerated values (extract "Constants for CFG-XXX" tables)
- R4/R8 = Floating point

REQUIRED JSON OUTPUT FORMAT:
{
  "keys": [
    {
      "name": "CFG-GROUP-ITEM",
      "key_id": "0xNNNNNNNN",
      "data_type": "E1",
      "description": "Description text",
      "scale": "1e-7",
      "unit": "deg",
      "inline_enum": {
        "values": {
          "CONSTANT_NAME": {"value": 0, "description": "What this value means"},
          "ANOTHER_CONST": {"value": 1, "description": "Another option"}
        }
      },
      "bitfield": {
        "bits": [
          {"name": "bitName", "bit_start": 0, "bit_end": 0, "description": "Bit meaning"}
        ]
      }
    }
  ]
}

CRITICAL EXTRACTION RULES:

1. FIELD NAMES: Use exactly these names:
   - "name" (not "key_name")
   - "key_id" (not "id")
   - "data_type" (not "type")
   - "inline_enum" (not "enum" or "constants")
   - "bitfield" (not "bits")

2. FOR E-TYPE KEYS (E1, E2, E4) - CRITICAL:
   - Look for "Constants for CFG-XXX-YYY" tables IMMEDIATELY after the key definition
   - These tables have columns: Name, Value, Description
   - Extract ALL constants into inline_enum.values
   - Each constant needs: name as key, value (integer), description (string)

3. FOR X-TYPE KEYS (X1, X2, X4):
   - Look for bit definition tables showing individual bit meanings
   - Extract into bitfield.bits array
   - Each bit needs: name, bit_start, bit_end, description

4. OMIT scale/unit if the table shows "-"

5. Extract EVERY key from EVERY CFG-XXX group. Do not skip any.

Return JSON with a "keys" array containing ALL extracted keys with complete enum/bitfield data.
"""


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def cost(self, model: str) -> float:
        p = PRICING.get(model, {"input": 0.15, "output": 0.60})
        return (self.input_tokens * p["input"] + self.output_tokens * p["output"]) / 1_000_000


def discover_config_section_pages(pdf_path: Path) -> tuple[int, int] | None:
    """Find the entire Configuration interface section (6.1-6.9).
    
    Returns (start_page, end_page) or None if not found.
    """
    doc = fitz.open(str(pdf_path))
    toc = doc.get_toc()
    doc.close()
    
    config_start = None
    next_major_section = None
    config_level = None
    
    for level, title, page in toc:
        # Find "Configuration interface" section start
        if config_start is None and "Configuration interface" in title:
            config_start = page
            config_level = level
            continue
        
        # Find next section at same level (end of config section)
        if config_start and config_level and level == config_level:
            next_major_section = page
            break
    
    if config_start and next_major_section:
        return (config_start, next_major_section - 1)
    
    return None


def discover_config_groups_from_toc(pdf_path: Path) -> dict:
    """Discover intro pages and per-group page ranges from TOC.
    
    Returns dict with:
      - intro_pages: (start, end) for section 6.1-6.8 intro content
      - groups: dict mapping group name to (start, end) page tuple
    """
    doc = fitz.open(str(pdf_path))
    toc = doc.get_toc()
    doc.close()
    
    result = {"intro_pages": None, "groups": {}}
    
    config_start = None
    config_level = None
    reference_start = None
    reference_level = None
    groups = []
    next_major_section = None
    
    for i, (level, title, page) in enumerate(toc):
        # Find "Configuration interface" section
        if config_start is None and "Configuration interface" in title:
            config_start = page
            config_level = level
            continue
        
        # Find "Configuration reference" subsection (6.9)
        if config_start and reference_start is None:
            if "Configuration" in title and "reference" in title.lower():
                reference_start = page
                reference_level = level
                # Intro pages are from config_start to just before reference
                result["intro_pages"] = (config_start, page - 1)
                continue
        
        # Find CFG-XXX groups within reference section
        if reference_start and level == reference_level + 1:
            match = re.match(r'.*?(CFG-[A-Z0-9]+)', title)
            if match:
                groups.append((match.group(1), page))
        
        # Find end of config section
        if config_start and config_level and level == config_level and page > config_start:
            next_major_section = page
            break
    
    # Calculate page ranges for each group
    for i, (group_name, start_page) in enumerate(groups):
        if i + 1 < len(groups):
            # End page is one before next group starts
            next_start = groups[i + 1][1]
            end_page = max(start_page, next_start - 1)
        else:
            end_page = (next_major_section - 1) if next_major_section else start_page + 5
        result["groups"][group_name] = (start_page, end_page)
    
    return result


def extract_pdf_pages(pdf_path: Path, page_start: int, page_end: int) -> bytes:
    """Extract page range from PDF as new PDF bytes."""
    doc = fitz.open(str(pdf_path))
    new_doc = fitz.open()
    
    # fitz uses 0-indexed pages
    for page_num in range(page_start - 1, page_end):
        if page_num < len(doc):
            new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
    
    pdf_bytes = new_doc.tobytes()
    new_doc.close()
    doc.close()
    
    return pdf_bytes


def extract_pdf_with_intro_and_pages(
    pdf_path: Path, 
    intro_pages: tuple[int, int],
    content_pages: tuple[int, int]
) -> bytes:
    """Extract PDF with intro pages + specific content pages."""
    doc = fitz.open(str(pdf_path))
    new_doc = fitz.open()
    
    # Add intro pages (1-indexed to 0-indexed)
    for page_num in range(intro_pages[0] - 1, intro_pages[1]):
        if page_num < len(doc):
            new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
    
    # Add content pages
    for page_num in range(content_pages[0] - 1, content_pages[1]):
        if page_num < len(doc):
            new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
    
    pdf_bytes = new_doc.tobytes()
    new_doc.close()
    doc.close()
    
    return pdf_bytes


# Known OCR error patterns to fix in key names
OCR_NAME_FIXES = {
    # I vs 1 confusion
    "CFG-12C": "CFG-I2C",
    "CFG-12CINPROT": "CFG-I2CINPROT",
    "CFG-12COUTPROT": "CFG-I2COUTPROT",
    # O vs 0 confusion (if any)
    "CFG-0DO": "CFG-ODO",
    # ENA vs ENNA typo
    "_ENNA": "_ENA",
}

# Known OCR error patterns to fix in data types
OCR_TYPE_FIXES = {
    "14": "I4",  # I vs 1 confusion
    "11": "I1",
    "12": "I2",
    "18": "I8",
}

# Valid unit abbreviations (for detecting description-as-unit errors)
VALID_UNITS = {
    "m", "s", "Hz", "deg", "%", "ms", "us", "km", "cm", "dBHz", "m/s", 
    "arcsec", "ppm", "g", "S", "m (or m/s)", "m (or\nm/s)", "-"
}

# Units that should be lowercase
UNIT_CASE_FIXES = {
    "S": "s",  # seconds
}

# Unicode lookalike character mappings (Greek/Cyrillic -> Latin)
UNICODE_LOOKALIKES = {
    # Greek letters that look like Latin
    '\u0391': 'A',  # Α (Greek Alpha) -> A
    '\u0392': 'B',  # Β (Greek Beta) -> B
    '\u0395': 'E',  # Ε (Greek Epsilon) -> E
    '\u0396': 'Z',  # Ζ (Greek Zeta) -> Z
    '\u0397': 'H',  # Η (Greek Eta) -> H
    '\u0399': 'I',  # Ι (Greek Iota) -> I
    '\u039A': 'K',  # Κ (Greek Kappa) -> K
    '\u039C': 'M',  # Μ (Greek Mu) -> M
    '\u039D': 'N',  # Ν (Greek Nu) -> N
    '\u039F': 'O',  # Ο (Greek Omicron) -> O
    '\u03A1': 'P',  # Ρ (Greek Rho) -> P
    '\u03A4': 'T',  # Τ (Greek Tau) -> T
    '\u03A5': 'Y',  # Υ (Greek Upsilon) -> Y
    '\u03A7': 'X',  # Χ (Greek Chi) -> X
    # Cyrillic letters that look like Latin
    '\u0410': 'A',  # А (Cyrillic A) -> A
    '\u0412': 'B',  # В (Cyrillic Ve) -> B
    '\u0415': 'E',  # Е (Cyrillic Ie) -> E
    '\u041A': 'K',  # К (Cyrillic Ka) -> K
    '\u041C': 'M',  # М (Cyrillic Em) -> M
    '\u041D': 'H',  # Н (Cyrillic En) -> H
    '\u041E': 'O',  # О (Cyrillic O) -> O
    '\u0420': 'P',  # Р (Cyrillic Er) -> P
    '\u0421': 'C',  # С (Cyrillic Es) -> C
    '\u0422': 'T',  # Т (Cyrillic Te) -> T
    '\u0423': 'Y',  # У (Cyrillic U) -> Y
    '\u0425': 'X',  # Х (Cyrillic Ha) -> X
    '\u0417': '3',  # З (Cyrillic Ze) -> 3
}


def normalize_unicode(text: str) -> str:
    """Replace visually similar Greek/Cyrillic characters with ASCII equivalents."""
    for lookalike, ascii_char in UNICODE_LOOKALIKES.items():
        text = text.replace(lookalike, ascii_char)
    return text


def fix_ocr_errors(keys: list[dict]) -> list[dict]:
    """Fix common OCR errors in extracted key names and data types."""
    fixed_keys = []
    fixes_applied = 0
    
    for key in keys:
        name = key.get("name", "")
        data_type = key.get("data_type", "")
        description = key.get("description", "")
        scale = key.get("scale")
        unit = key.get("unit")
        
        # Normalize Unicode lookalikes first
        new_name = normalize_unicode(name)
        new_desc = normalize_unicode(description)
        
        # Fix spaces to underscores in key names (after CFG-GROUP- prefix)
        # e.g., "CFG-TMODE-HEIGHT HP" -> "CFG-TMODE-HEIGHT_HP"
        if " " in new_name and new_name.startswith("CFG-"):
            new_name = new_name.replace(" ", "_")
        
        # Fix name OCR errors
        for wrong, correct in OCR_NAME_FIXES.items():
            if wrong in new_name:
                new_name = new_name.replace(wrong, correct)
        
        # Fix data type OCR errors
        new_type = OCR_TYPE_FIXES.get(data_type, data_type)
        
        # Fix scale/unit confusion
        new_scale = scale
        new_unit = unit
        
        # If scale looks like a unit, it's probably a 5-column table (no Scale column)
        # Move scale value to unit if unit is empty or looks like description
        if scale in ("m", "s", "Hz", "deg", "ms", "us", "km", "cm", "arcsec", "ppm", "dBHz", "g", "%", "m/s"):
            if unit is None or len(str(unit)) > 15:  # Unit is empty or looks like description
                new_unit = scale
            new_scale = None
        
        # Remove placeholder scale values
        if scale == "1" or scale == "-" or scale == "None":
            new_scale = None
        
        # Fix unit issues
        if unit == "-" or unit == "1" or unit == "None":
            new_unit = None
        
        # If unit looks like a description (too long), remove it
        if new_unit and len(str(new_unit)) > 15:
            new_unit = None
        
        # Fix unit case (S -> s for seconds)
        if new_unit in UNIT_CASE_FIXES:
            new_unit = UNIT_CASE_FIXES[new_unit]
        
        # Normalize newlines in units
        if new_unit and "\n" in new_unit:
            new_unit = new_unit.replace("\n", " ")
        
        modified = False
        if new_name != name or new_type != data_type or new_desc != description:
            modified = True
        if new_scale != scale or new_unit != unit:
            modified = True
        
        if modified:
            key = key.copy()
            if new_name != name:
                key["name"] = new_name
            if new_type != data_type:
                key["data_type"] = new_type
            if new_desc != description:
                key["description"] = new_desc
            if new_scale != scale:
                if new_scale is None and "scale" in key:
                    del key["scale"]
                elif new_scale is not None:
                    key["scale"] = new_scale
            if new_unit != unit:
                if new_unit is None and "unit" in key:
                    del key["unit"]
                elif new_unit is not None:
                    key["unit"] = new_unit
            fixes_applied += 1
        
        fixed_keys.append(key)
    
    if fixes_applied:
        print(f"    Fixed {fixes_applied} OCR/Unicode/formatting errors")
    
    return fixed_keys


def batch_groups_by_page_count(
    groups: dict[str, tuple[int, int]], 
    max_pages: int = 15
) -> list[dict]:
    """Batch consecutive groups together based on page count.
    
    Returns list of batches, each with:
      - groups: list of group names
      - page_start: first page
      - page_end: last page
      - page_count: total pages
    """
    batches = []
    current_batch = {"groups": [], "page_start": None, "page_end": None}
    
    for group_name, (start, end) in sorted(groups.items(), key=lambda x: x[1][0]):
        group_pages = end - start + 1
        
        if current_batch["page_start"] is None:
            # Start new batch
            current_batch = {
                "groups": [group_name],
                "page_start": start,
                "page_end": end,
            }
        else:
            # Calculate what total pages would be if we add this group
            new_end = max(current_batch["page_end"], end)
            total_pages = new_end - current_batch["page_start"] + 1
            
            if total_pages <= max_pages:
                # Add to current batch
                current_batch["groups"].append(group_name)
                current_batch["page_end"] = new_end
            else:
                # Save current batch and start new one
                current_batch["page_count"] = current_batch["page_end"] - current_batch["page_start"] + 1
                batches.append(current_batch)
                current_batch = {
                    "groups": [group_name],
                    "page_start": start,
                    "page_end": end,
                }
    
    # Don't forget last batch
    if current_batch["groups"]:
        current_batch["page_count"] = current_batch["page_end"] - current_batch["page_start"] + 1
        batches.append(current_batch)
    
    return batches


def call_gemini(
    pdf_bytes: bytes,
    model: str = "gemini-2.5-flash-lite",
    group_list: list[str] | None = None,
    verbose: bool = True,
) -> tuple[dict[str, Any], TokenUsage]:
    """Call Gemini API with native PDF upload using new google-genai SDK."""
    from google import genai
    
    # Select prompt based on whether this is batch or full extraction
    if group_list:
        prompt = GEMINI_BATCH_PROMPT.format(group_list=", ".join(group_list))
    else:
        prompt = GEMINI_PROMPT
    
    client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))
    
    # Save PDF to temp file for upload
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        temp_path = f.name
    
    try:
        if verbose:
            print("    Uploading PDF to Gemini...")
        uploaded_file = client.files.upload(file=temp_path)
        
        if verbose:
            print("    Calling Gemini API...")
        start_time = time.time()
        
        # Retry with exponential backoff for rate limits
        max_retries = 5
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=[uploaded_file, prompt],
                    config={
                        "response_mime_type": "application/json",
                        "max_output_tokens": 65536,
                    },
                )
                break  # Success
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    wait_time = 30 * (2 ** attempt)  # 30s, 60s, 120s, 240s, 480s
                    if verbose:
                        print(f"    Rate limited, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)
                    if attempt == max_retries - 1:
                        raise
                else:
                    raise
        
        elapsed = time.time() - start_time
        if verbose:
            print(f"    Response received in {elapsed:.1f}s")
        
    finally:
        os.unlink(temp_path)
    
    # Parse response
    try:
        result = json.loads(response.text)
    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}")
        print(f"  Response length: {len(response.text)} chars")
        print(f"  First 500 chars: {response.text[:500]}")
        result = {"error": "Failed to parse JSON", "raw": response.text[:2000]}
    
    # Get usage stats
    usage = TokenUsage()
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        usage.input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        usage.output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
    
    return result, usage


def main():
    parser = argparse.ArgumentParser(description="Extract config keys with Gemini (batched by page count)")
    parser.add_argument("--pdf-path", type=Path, required=True)
    parser.add_argument("--model", choices=list(GEMINI_MODELS.keys()), default="flash-lite")
    parser.add_argument("--out-dir", type=Path, default=Path("data/config_keys/by-manual"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-pages", type=int, default=15, help="Max pages per batch (default: 15)")
    parser.add_argument("--groups", nargs="*", help="Specific groups to extract (default: all)")
    args = parser.parse_args()
    
    model = GEMINI_MODELS[args.model]
    
    if not args.dry_run and not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set")
        return 1
    print(f"Model: {model}")
    print(f"Processing: {args.pdf_path.name}")
    
    # Discover intro pages and per-group page ranges from TOC
    config_info = discover_config_groups_from_toc(args.pdf_path)
    
    if not config_info["intro_pages"]:
        print("  Error: Could not find Configuration interface intro section")
        return 1
    
    if not config_info["groups"]:
        print("  Error: Could not find any CFG-XXX groups in TOC")
        return 1
    
    intro_pages = config_info["intro_pages"]
    all_groups = config_info["groups"]
    
    print(f"  Intro pages: {intro_pages[0]}-{intro_pages[1]} ({intro_pages[1] - intro_pages[0] + 1} pages)")
    print(f"  Found {len(all_groups)} groups in TOC")
    
    # Filter groups if specified
    if args.groups:
        groups_to_extract = {g: p for g, p in all_groups.items() if g in args.groups}
        print(f"  Extracting {len(groups_to_extract)} specified groups")
    else:
        groups_to_extract = all_groups
    
    # Create batches by page count
    batches = batch_groups_by_page_count(groups_to_extract, max_pages=args.max_pages)
    print(f"  Created {len(batches)} batches (max {args.max_pages} pages each)")
    
    if args.dry_run:
        print("\n  [DRY RUN] Would extract these batches:")
        for i, batch in enumerate(batches, 1):
            groups_str = ", ".join(batch["groups"])
            print(f"    Batch {i}: pages {batch['page_start']}-{batch['page_end']} ({batch['page_count']} pages)")
            print(f"      Groups: {groups_str}")
        return 0
    
    # Extract each batch with intro context
    all_keys = []
    total_usage = TokenUsage()
    
    for i, batch in enumerate(batches, 1):
        groups_str = ", ".join(batch["groups"])
        print(f"\n  Batch {i}/{len(batches)}: pages {batch['page_start']}-{batch['page_end']} ({batch['page_count']} pages)")
        print(f"    Groups: {groups_str}")
        
        # Create PDF with intro + this batch's pages
        content_pages = (batch["page_start"], batch["page_end"])
        pdf_bytes = extract_pdf_with_intro_and_pages(args.pdf_path, intro_pages, content_pages)
        print(f"    PDF size: {len(pdf_bytes) / 1024:.1f} KB")
        
        result, usage = call_gemini(pdf_bytes, model, group_list=batch["groups"], verbose=True)
        
        total_usage.input_tokens += usage.input_tokens
        total_usage.output_tokens += usage.output_tokens
        
        if "error" in result:
            print(f"    Error: {result['error']}")
            continue
        
        batch_keys = result.get("keys", [])
        batch_keys = fix_ocr_errors(batch_keys)
        all_keys.extend(batch_keys)
        print(f"    Extracted {len(batch_keys)} keys")
    
    # Use combined keys from all batches
    keys = all_keys
    
    # Deduplicate by name
    seen = set()
    unique_keys = []
    for key in keys:
        name = key.get("name", "")
        if name and name not in seen:
            seen.add(name)
            unique_keys.append(key)
    
    # Group by CFG-XXX
    groups = {}
    for key in unique_keys:
        name = key.get("name", "")
        match = re.match(r'(CFG-[A-Z0-9]+)-', name)
        if match:
            group = match.group(1)
            if group not in groups:
                groups[group] = []
            groups[group].append(key)
    
    # Print summary
    print(f"\n  Results:")
    print(f"    Total keys: {len(unique_keys)}")
    print(f"    Groups: {len(groups)}")
    print(f"    Tokens: {total_usage.input_tokens:,} in / {total_usage.output_tokens:,} out")
    print(f"    Cost: ${total_usage.cost(model):.4f}")
    
    # Show per-group counts
    print(f"\n  Keys per group:")
    for group in sorted(groups.keys()):
        print(f"    {group}: {len(groups[group])} keys")
    
    # Save output
    if unique_keys:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        out_file = args.out_dir / f"{args.pdf_path.stem}_gemini_config_keys.json"
        
        output = {
            "schema_version": "1.0",
            "source_document": {"filename": args.pdf_path.name},
            "extraction_metadata": {
                "model": model,
                "intro_pages": f"{intro_pages[0]}-{intro_pages[1]}",
                "batches": len(batches),
                "max_pages_per_batch": args.max_pages,
                "groups_extracted": len(groups_to_extract),
                "tokens": {"input": total_usage.input_tokens, "output": total_usage.output_tokens},
                "cost_usd": round(total_usage.cost(model), 4),
            },
            "groups": {g: {"name": g, "keys": k} for g, k in sorted(groups.items())},
            "keys": unique_keys,
            "_stats": {
                "total_keys": len(unique_keys),
                "total_groups": len(groups),
            },
        }
        
        out_file.write_text(json.dumps(output, indent=2))
        print(f"\n  Saved: {out_file}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
