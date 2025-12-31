#!/usr/bin/env python3
"""Extract configuration keys using Gemini with per-group requests.

Strategy:
1. Upload config section PDF once (intro + all group pages)
2. Extract ONE group per API call (better focus, no truncation)
3. Default: Gemini 3 Flash (best quality/cost ratio, zero OCR errors)

Model comparison (M9-SPG manual):
    - flash-lite: $0.08, 5 min, 5 OCR errors
    - 3-flash:    $0.70, 15 min, 0 OCR errors  <-- DEFAULT
    - 3-pro:      $1.52, 25 min, 0 OCR errors

Usage:
    export GOOGLE_API_KEY="your-api-key"
    uv run python scripts/extract_config_keys_pergroup.py --pdf-path <path>
    uv run python scripts/extract_config_keys_pergroup.py --pdf-path <path> --model flash-lite
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

# Available models
GEMINI_MODELS = {
    "flash-lite": "gemini-2.5-flash-lite",
    "flash": "gemini-2.5-flash",
    "pro": "gemini-2.5-pro",
    "3-flash": "gemini-3-flash-preview",
    "3-pro": "gemini-3-pro-preview",
}

PRICING = {
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    "gemini-3-pro-preview": {"input": 1.25, "output": 10.00},
}

# Prompt for single-group extraction
SINGLE_GROUP_PROMPT = """You are extracting UBX configuration key definitions from a u-blox interface description PDF.

TASK: Extract ONLY the keys from group: {group_name}

The PDF contains the full configuration interface section. Focus ONLY on {group_name} keys.

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

=== KEY NAME FORMATTING ===

Key names use UNDERSCORES, never spaces. Examples:
- CORRECT: CFG-TMODE-HEIGHT_HP
- WRONG: CFG-TMODE-HEIGHT HP

=== NAV vs NAV2 MESSAGE OUTPUT KEYS ===

CRITICAL: The CFG-MSGOUT group contains BOTH "NAV" and "NAV2" message keys.
These are DIFFERENT keys with DIFFERENT key_ids:
- CFG-MSGOUT-UBX_NAV_PVT_* = NAV-PVT message output (older)
- CFG-MSGOUT-UBX_NAV2_PVT_* = NAV2-PVT message output (newer)

When extracting from CFG-MSGOUT tables:
1. Read the EXACT key name from the table - do not modify NAV/NAV2
2. The key_id (hex value) is DIFFERENT for NAV vs NAV2 variants
3. Double-check each key: Does the name say "NAV_" or "NAV2_"?

=== TABLE STRUCTURE ===

Config key tables have either 5 or 6 columns:
- 6 columns: Key name | Key ID | Hex ID | Type | Scale | Unit | Description
- 5 columns: Key name | Key ID | Hex ID | Type | Description (NO Scale/Unit)

If there is NO Scale column, leave scale as null. Do NOT put description text in scale field.

=== OUTPUT FORMAT ===

Return a JSON object with this structure:
{{
  "group": "{group_name}",
  "keys": [
    {{
      "name": "CFG-XXX-KEYNAME",
      "key_id": "0x12345678",
      "data_type": "U4",
      "description": "Description text",
      "scale": "1e-7" or null,
      "unit": "deg" or null,
      "inline_enum": {{ "values": {{ "NAME": {{"value": 0, "description": "..."}} }} }} or null,
      "bitfield": {{ "bits": [...] }} or null
    }}
  ]
}}

Extract ALL keys for {group_name}. Be thorough and accurate."""


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    
    def cost(self, model: str) -> float:
        pricing = PRICING.get(model, PRICING["gemini-2.5-pro"])
        return (self.input_tokens * pricing["input"] + self.output_tokens * pricing["output"]) / 1_000_000


def discover_config_section(pdf_path: Path) -> dict:
    """Find config interface section pages from TOC.
    
    Uses TOC hierarchy - doesn't assume specific section numbers.
    
    Returns dict with:
      - intro_pages: (start, end) for section intro content
      - config_end: last page of config section
      - groups: dict mapping group name to (start, end) page tuple
    """
    doc = fitz.open(str(pdf_path))
    toc = doc.get_toc()
    doc.close()
    
    result = {"intro_pages": None, "config_end": None, "groups": {}}
    
    # Step 1: Find "Configuration interface" section
    config_idx = None
    config_level = None
    config_start = None
    
    for i, (level, title, page) in enumerate(toc):
        if "Configuration interface" in title:
            config_idx = i
            config_level = level
            config_start = page
            break
    
    if config_idx is None:
        return result
    
    # Step 2: Find end of config section (next entry at same level)
    config_end_page = None
    for i in range(config_idx + 1, len(toc)):
        level, title, page = toc[i]
        if level <= config_level:
            config_end_page = page - 1
            break
    
    # Step 3: Find "Configuration reference" subsection and CFG-XXX groups
    reference_idx = None
    reference_level = None
    groups = []
    
    for i in range(config_idx + 1, len(toc)):
        level, title, page = toc[i]
        
        # Stop if we've left the config section
        if level <= config_level:
            break
        
        # Find the reference subsection
        if reference_idx is None and "reference" in title.lower():
            reference_idx = i
            reference_level = level
            result["intro_pages"] = (config_start, page - 1)
            continue
        
        # After finding reference, look for CFG-XXX entries
        if reference_idx is not None:
            match = re.search(r'(CFG-[A-Z0-9]+)', title)
            if match:
                groups.append((match.group(1), page, i))
    
    # Step 4: Calculate group page ranges using TOC order
    # Sort groups by page to handle out-of-order TOC entries
    groups_sorted = sorted(groups, key=lambda x: x[1])
    for idx, (name, start, toc_idx) in enumerate(groups_sorted):
        if idx + 1 < len(groups_sorted):
            end = groups_sorted[idx + 1][1] - 1
        elif config_end_page:
            end = config_end_page
        else:
            end = start + 10  # Fallback
        # Ensure end >= start
        end = max(end, start)
        result["groups"][name] = (start, end)
    
    # Config section end
    if result["groups"]:
        result["config_end"] = max(end for _, end in result["groups"].values())
    elif config_end_page:
        result["config_end"] = config_end_page
    
    return result


def create_config_section_pdf(source_pdf: Path, start_page: int, end_page: int) -> Path:
    """Extract config section to a temp PDF."""
    doc = fitz.open(source_pdf)
    new_doc = fitz.open()
    
    # Pages are 0-indexed in PyMuPDF, but TOC gives 1-indexed
    for page_num in range(start_page - 1, end_page):
        if page_num < len(doc):
            new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
    
    temp_path = tempfile.mktemp(suffix=".pdf")
    new_doc.save(temp_path)
    new_doc.close()
    doc.close()
    
    return Path(temp_path)


def extract_single_group(
    client,
    uploaded_file,
    group_name: str,
    model: str,
    verbose: bool = True,
) -> tuple[dict, TokenUsage]:
    """Extract a single group from the uploaded PDF."""
    
    prompt = SINGLE_GROUP_PROMPT.format(group_name=group_name)
    
    if verbose:
        print(f"  Extracting {group_name}...", end=" ", flush=True)
    
    start_time = time.time()
    
    # Retry with exponential backoff
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
            break
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                wait_time = 30 * (2 ** attempt)
                if verbose:
                    print(f"rate limited, waiting {wait_time}s...", end=" ", flush=True)
                time.sleep(wait_time)
                if attempt == max_retries - 1:
                    raise
            else:
                raise
    
    elapsed = time.time() - start_time
    
    # Parse response
    try:
        # Debug: check why response might be empty
        if response.text is None:
            # Check for finish reason
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                finish_reason = getattr(candidate, 'finish_reason', 'unknown')
                raise ValueError(f"Empty response - finish_reason: {finish_reason}")
            raise ValueError("Empty response from API (no candidates)")
        result = json.loads(response.text)
        key_count = len(result.get("keys", []))
        if verbose:
            print(f"{key_count} keys ({elapsed:.1f}s)")
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        if verbose:
            print(f"error: {e}")
        result = {"error": str(e), "group": group_name, "keys": []}
    
    # Get usage
    usage = TokenUsage()
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        usage.input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        usage.output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
    
    return result, usage


def post_process_keys(keys: list[dict]) -> list[dict]:
    """Apply OCR fixes and validation."""
    OCR_FIXES = {
        "CFG-12C": "CFG-I2C",
        "CFG-0DO": "CFG-ODO",
        "_ENNA": "_ENA",
        "_ENAA": "_ENA",
    }
    
    fixed = []
    for key in keys:
        name = key.get("name", "")
        
        # Apply OCR fixes
        for wrong, correct in OCR_FIXES.items():
            if wrong in name:
                name = name.replace(wrong, correct)
        
        # Fix spaces to underscores
        name = name.replace(" ", "_")
        
        key["name"] = name
        
        # Fix data type OCR errors
        dt = key.get("data_type", "")
        if dt in ("11", "12", "14", "18"):
            key["data_type"] = dt.replace("1", "I", 1)
        
        # Clean scale/unit
        if key.get("scale") in (None, "", "-", "1"):
            key.pop("scale", None)
        if key.get("unit") in (None, "", "-", "1"):
            key.pop("unit", None)
        
        fixed.append(key)
    
    return fixed


def main():
    parser = argparse.ArgumentParser(description="Extract config keys with Gemini (per-group)")
    parser.add_argument("--pdf-path", type=Path, required=True)
    parser.add_argument("--model", choices=list(GEMINI_MODELS.keys()), default="3-flash",
                        help="Model to use (default: 3-flash)")
    parser.add_argument("--out-dir", type=Path, default=Path("data/config_keys/by-manual"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--groups", nargs="*", help="Specific groups to extract")
    args = parser.parse_args()
    
    model = GEMINI_MODELS[args.model]
    
    if not args.dry_run and not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set")
        return 1
    
    print(f"Model: {model}")
    print(f"Processing: {args.pdf_path.name}")
    
    # Discover config section
    config_info = discover_config_section(args.pdf_path)
    
    if not config_info["intro_pages"]:
        print("  Error: Could not find Configuration interface section")
        return 1
    
    groups = config_info["groups"]
    if args.groups:
        groups = {g: p for g, p in groups.items() if g in args.groups}
    
    intro_start, intro_end = config_info["intro_pages"]
    print(f"  Intro pages: {intro_start}-{intro_end}")
    print(f"  Config section ends: page {config_info['config_end']}")
    print(f"  Groups to extract: {len(groups)}")
    
    if args.dry_run:
        print("\nDry run - groups found:")
        for g, (start, end) in sorted(groups.items()):
            print(f"  {g}: pages {start}-{end}")
        return 0
    
    # Create config section PDF (intro + all groups)
    print("\n  Creating config section PDF...")
    temp_pdf = create_config_section_pdf(
        args.pdf_path,
        intro_start,
        config_info["config_end"]
    )
    print(f"  Temp PDF: {temp_pdf}")
    
    # Initialize Gemini client
    from google import genai
    client = genai.Client()
    
    # Upload PDF once
    print("  Uploading PDF to Gemini...")
    uploaded_file = client.files.upload(file=temp_pdf)
    print(f"  Uploaded: {uploaded_file.name}")
    
    # Extract each group
    all_keys = []
    total_usage = TokenUsage()
    
    print(f"\nExtracting {len(groups)} groups:")
    for group_name in sorted(groups.keys()):
        result, usage = extract_single_group(
            client, uploaded_file, group_name, model
        )
        
        keys = result.get("keys", [])
        keys = post_process_keys(keys)
        all_keys.extend(keys)
        
        total_usage.input_tokens += usage.input_tokens
        total_usage.output_tokens += usage.output_tokens
    
    # Cleanup
    os.unlink(temp_pdf)
    
    # Deduplicate by key_id
    seen = set()
    unique_keys = []
    for key in all_keys:
        key_id = key.get("key_id", "")
        if key_id and key_id not in seen:
            seen.add(key_id)
            unique_keys.append(key)
    
    # Save output
    output = {
        "source_file": args.pdf_path.name,
        "extraction_model": model,
        "extraction_method": "per-group",
        "total_groups": len(groups),
        "keys": sorted(unique_keys, key=lambda k: k.get("name", "")),
    }
    
    # Output filename - include model name
    stem = args.pdf_path.stem
    if "_InterfaceDescription" in stem:
        stem = stem.split("_InterfaceDescription")[0]
    model_suffix = args.model.replace("-", "")  # e.g., "3pro", "flashlite", "3flash"
    out_file = args.out_dir / f"{stem}_{model_suffix}_config_keys.json"
    
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        json.dump(output, f, indent=2)
    
    # Summary
    cost = total_usage.cost(model)
    print(f"\n=== Summary ===")
    print(f"  Keys extracted: {len(unique_keys)}")
    print(f"  Input tokens: {total_usage.input_tokens:,}")
    print(f"  Output tokens: {total_usage.output_tokens:,}")
    print(f"  Estimated cost: ${cost:.4f}")
    print(f"  Output: {out_file}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
