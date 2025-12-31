#!/usr/bin/env python3
"""Extract UBX configuration keys from PDF pages using Anthropic Claude.

This script uses Claude's vision capabilities to parse PDF page images
and extract structured configuration key definitions into JSON format.

Config keys are used with CFG-VALGET/VALSET/VALDEL messages in F9+ receivers.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic
import fitz  # PyMuPDF for TOC access
import pdfplumber
from tqdm import tqdm

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.extraction.config_key_prompts import (
    build_config_key_prompt,
    build_config_key_tool_schema,
)
from src.extraction.pdf_utils import (
    extract_pages_as_images_cropped,
)


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass
class ConfigKeyExtractionResult:
    group_name: str
    success: bool
    keys: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    cache_key: str = ""
    usage: TokenUsage | None = None


@dataclass
class ConfigKeySection:
    """A config key group section from the TOC."""
    group_name: str
    page_start: int
    page_end: int


def discover_config_key_sections_from_toc(pdf_path: Path) -> list[ConfigKeySection]:
    """Discover config key sections from PDF TOC.
    
    Looks for "Configuration reference" section and CFG-XXX group entries.
    Returns list of ConfigKeySection with page ranges.
    """
    doc = fitz.open(str(pdf_path))
    toc = doc.get_toc()
    doc.close()
    
    # Find all CFG-XXX entries (config key groups, NOT UBX-CFG messages)
    cfg_entries = []
    for level, title, page in toc:
        # Match "CFG-XXX:" patterns (config key groups)
        # Skip "UBX-CFG-XXX" which are UBX messages
        if "CFG-" in title and "UBX-CFG" not in title:
            # Extract group name like "CFG-BDS", "CFG-RATE"
            match = re.search(r'(CFG-[A-Z0-9]+)(?::|$|\s)', title)
            if match:
                cfg_entries.append({
                    "group": match.group(1),
                    "title": title,
                    "page": page,
                    "level": level,
                })
    
    if not cfg_entries:
        return []
    
    # Sort by page
    cfg_entries.sort(key=lambda x: x["page"])
    
    # Build sections with page ranges
    sections = []
    for i, entry in enumerate(cfg_entries):
        page_start = entry["page"]
        # End page is start of next section, or +10 pages if last
        if i + 1 < len(cfg_entries):
            page_end = cfg_entries[i + 1]["page"]
        else:
            page_end = page_start + 10  # Generous buffer for last section
        
        sections.append(ConfigKeySection(
            group_name=entry["group"],
            page_start=page_start,
            page_end=page_end,
        ))
    
    return sections


def discover_all_config_key_pages(pdf_path: Path, show_progress: bool = False) -> tuple[int, int] | None:
    """Find the page range containing all configuration keys using TOC.
    
    Returns (start_page, end_page) tuple, or None if not found.
    """
    sections = discover_config_key_sections_from_toc(pdf_path)
    
    if not sections:
        return None
    
    # Get overall range from first to last section
    start_page = sections[0].page_start
    end_page = sections[-1].page_end
    
    return (start_page, end_page)


def hash_image(img_bytes: bytes) -> str:
    """Hash image bytes for cache key computation."""
    return hashlib.sha256(img_bytes).hexdigest()[:12]


def compute_cache_key(
    pdf_path: str,
    page_range: tuple[int, int],
    page_hashes: list[str],
    model: str,
) -> str:
    """Compute a deterministic cache key for extraction results."""
    key_data = {
        "pdf": pdf_path,
        "pages": f"{page_range[0]}-{page_range[1]}",
        "hashes": sorted(page_hashes),
        "model": model,
        "prompt_version": "1.0",
    }
    key_str = json.dumps(key_data, sort_keys=True)
    return hashlib.sha256(key_str.encode()).hexdigest()[:16]


def load_cache(cache_dir: Path) -> dict[str, Any]:
    """Load extraction cache from disk."""
    cache_file = cache_dir / "config_key_cache.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache_dir: Path, cache: dict[str, Any]) -> None:
    """Save extraction cache to disk."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "config_key_cache.json"
    cache_file.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def call_claude_for_config_keys(
    images: list[bytes],
    group_name: str,
    group_description: str,
    model: str,
    max_tokens: int = 16384,
) -> tuple[dict[str, Any], TokenUsage]:
    """Call Claude API to extract config keys from PDF page images."""
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
    
    prompt = build_config_key_prompt(group_name, group_description)
    content.append({"type": "text", "text": prompt})
    
    tool = build_config_key_tool_schema()
    
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


def validate_config_key_extraction(result: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """Validate extracted config keys."""
    errors: list[str] = []
    warnings: list[str] = []
    
    if "error" in result:
        errors.append(str(result["error"]))
        return False, errors, warnings
    
    keys = result.get("keys", [])
    if not keys:
        warnings.append("No config keys extracted")
    
    seen_ids = set()
    seen_names = set()
    
    for i, key in enumerate(keys):
        name = key.get("name", "")
        key_id = key.get("key_id", "")
        data_type = key.get("data_type", "")
        
        if not name:
            errors.append(f"Key {i}: missing name")
        elif not name.startswith("CFG-"):
            errors.append(f"Key {i}: name '{name}' doesn't start with CFG-")
        
        if not key_id:
            errors.append(f"Key {i} ({name}): missing key_id")
        elif not re.match(r"^0x[0-9a-fA-F]{8}$", key_id):
            errors.append(f"Key {i} ({name}): invalid key_id format '{key_id}'")
        elif key_id in seen_ids:
            warnings.append(f"Key {i} ({name}): duplicate key_id {key_id}")
        else:
            seen_ids.add(key_id)
        
        if name in seen_names:
            warnings.append(f"Key {i}: duplicate name '{name}'")
        else:
            seen_names.add(name)
        
        if not data_type:
            errors.append(f"Key {i} ({name}): missing data_type")
        
        # Check for enum on E-type
        if data_type and data_type.startswith("E") and "inline_enum" not in key:
            warnings.append(f"Key {name}: E-type without inline_enum")
        
        # Check for bitfield on X-type
        if data_type and data_type.startswith("X") and "bitfield" not in key:
            warnings.append(f"Key {name}: X-type without bitfield")
    
    return len(errors) == 0, errors, warnings


def extract_config_keys_for_group(
    pdf_path: Path,
    group: ConfigKeySection,
    args: argparse.Namespace,
    cache: dict,
    cache_dir: Path,
    max_pages_per_call: int = 6,
    show_progress: bool = True,
) -> ConfigKeyExtractionResult:
    """Extract config keys for a single group from its page range.
    
    For large groups (many pages), splits into chunks to avoid token limits.
    """
    total_pages = group.page_end - group.page_start + 1
    all_keys = []
    total_usage = TokenUsage()
    all_errors = []
    all_warnings = []
    
    # Calculate number of chunks
    num_chunks = (total_pages + max_pages_per_call - 1) // max_pages_per_call
    chunk_idx = 0
    
    # Process in chunks if group spans many pages
    page_start = group.page_start
    while page_start <= group.page_end:
        page_end = min(page_start + max_pages_per_call - 1, group.page_end)
        chunk_idx += 1
        
        # Show progress for multi-chunk groups
        if show_progress and num_chunks > 1:
            tqdm.write(f"      {group.group_name} chunk {chunk_idx}/{num_chunks} (pages {page_start}-{page_end})")
        
        images = extract_pages_as_images_cropped(
            pdf_path,
            page_start,
            page_end,
            crop_top_ratio=args.crop_top_ratio,
            crop_bottom_ratio=args.crop_bottom_ratio,
        )
        
        page_hashes = [hash_image(img) for img in images]
        cache_key = compute_cache_key(
            str(pdf_path),
            (page_start, page_end),
            page_hashes,
            args.model,
        )
        
        if args.use_cache and not args.force and cache_key in cache:
            cached = cache[cache_key]
            keys_from_cache = cached.get("keys", [])
            all_keys.extend(keys_from_cache)
            if show_progress and num_chunks > 1:
                tqdm.write(f"        [cached] {len(keys_from_cache)} keys")
            page_start = page_end + 1
            continue
        
        try:
            raw, usage = call_claude_for_config_keys(
                images=images,
                group_name=group.group_name,
                group_description="",
                model=args.model,
                max_tokens=args.max_tokens,
            )
        except Exception as e:
            all_errors.append(f"Pages {page_start}-{page_end}: {str(e)}")
            page_start = page_end + 1
            continue
        
        if usage:
            total_usage.input_tokens += usage.input_tokens
            total_usage.output_tokens += usage.output_tokens
        
        valid, errors, warnings = validate_config_key_extraction(raw)
        all_errors.extend(errors)
        all_warnings.extend(warnings)
        
        keys = raw.get("keys", [])
        all_keys.extend(keys)
        
        if show_progress and num_chunks > 1:
            tqdm.write(f"        extracted {len(keys)} keys")
        
        if valid and args.use_cache:
            cache[cache_key] = raw
            save_cache(cache_dir, cache)
        
        page_start = page_end + 1
    
    return ConfigKeyExtractionResult(
        group_name=group.group_name,
        success=len(all_errors) == 0,
        keys=all_keys,
        errors=all_errors,
        warnings=all_warnings,
        cache_key="",
        usage=total_usage if total_usage.input_tokens > 0 else None,
    )


def get_unique_manuals_from_json(manuals_json: Path) -> list[dict]:
    """Get unique interface description manuals that have config keys (F9+)."""
    data = json.loads(manuals_json.read_text(encoding="utf-8"))
    
    seen_titles = set()
    unique_manuals = []
    
    # Patterns indicating F9+ generation (have config keys)
    f9_plus_patterns = [
        "F9", "F10", "M9", "M10", "X20", "F20",
        "HPG", "HPS", "LAP", "SPG-4", "SPG-5", "SPG-6",
        "ADR", "MDR", "DBD"
    ]
    
    for module_name, module_data in data.items():
        for manual in module_data.get("manuals", []):
            title = manual.get("title", "")
            
            # Skip if not an interface description
            title_lower = title.lower()
            if "interfacedescription" not in title_lower and "protspec" not in title_lower:
                continue
            
            # Skip M8 and earlier (no config keys)
            if "M8" in title and "F9" not in title:
                continue
            if "u-blox8" in title.lower():
                continue
            
            # Check if it's F9+ generation
            has_config_keys = any(pat in title for pat in f9_plus_patterns)
            if not has_config_keys:
                continue
            
            if title not in seen_titles:
                seen_titles.add(title)
                unique_manuals.append({
                    "title": title,
                    "local_path": manual.get("local_path"),
                    "url": manual.get("url"),
                })
    
    return unique_manuals


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract UBX configuration keys from PDF pages using Claude."
    )
    
    pdf_group = parser.add_mutually_exclusive_group(required=False)
    pdf_group.add_argument("--pdf-path", type=Path, help="Path to a local PDF")
    pdf_group.add_argument(
        "--all-manuals",
        action="store_true",
        help="Extract from all F9+ manuals in interface_manuals/manuals.json"
    )
    
    parser.add_argument(
        "--page-start",
        type=int,
        help="Start page for extraction (1-indexed)"
    )
    parser.add_argument(
        "--page-end",
        type=int,
        help="End page for extraction (1-indexed)"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Maximum pages to process in a single API call (default: 10)"
    )
    
    parser.add_argument("--model", type=str, default="claude-sonnet-4-20250514")
    parser.add_argument("--max-tokens", type=int, default=16384)
    
    parser.add_argument(
        "--crop-top-ratio",
        type=float,
        default=0.095,
        help="Crop fraction from top of pages (default: 0.095)"
    )
    parser.add_argument(
        "--crop-bottom-ratio",
        type=float,
        default=0.085,
        help="Crop fraction from bottom of pages (default: 0.085)"
    )
    
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/config_keys/by-manual"),
        help="Output directory for extracted JSON files"
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Use cached extractions if available"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-extraction even if cached"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be extracted without calling API"
    )
    
    return parser.parse_args()


def process_single_pdf(
    pdf_path: Path,
    args: argparse.Namespace,
    cache: dict,
    cache_dir: Path,
) -> tuple[int, list[dict]]:
    """Process a single PDF and extract config keys group by group.
    
    Returns (key_count, keys_list).
    """
    print(f"\nProcessing: {pdf_path.name}")
    
    # Discover config key groups from TOC
    groups = discover_config_key_sections_from_toc(pdf_path)
    if not groups:
        print("  No config key groups found in TOC")
        return 0, []
    
    print(f"  Found {len(groups)} config key groups")
    
    if args.dry_run:
        for g in groups[:10]:
            print(f"    {g.group_name}: pages {g.page_start}-{g.page_end}")
        if len(groups) > 10:
            print(f"    ... and {len(groups) - 10} more")
        print("  [DRY RUN] Would extract these groups")
        return 0, []
    
    # Process each group
    all_keys = []
    total_usage = TokenUsage()
    
    with tqdm(groups, desc="  Extracting groups", unit="grp", leave=False) as pbar:
        for group in pbar:
            pbar.set_postfix_str(group.group_name)
            
            result = extract_config_keys_for_group(
                pdf_path, group, args, cache, cache_dir
            )
            
            status = "✅" if result.success else "❌"
            tqdm.write(f"    {group.group_name}: {status} ({len(result.keys)} keys)")
            
            if result.errors:
                for err in result.errors[:2]:
                    tqdm.write(f"      Error: {err}")
            
            if result.usage:
                total_usage.input_tokens += result.usage.input_tokens
                total_usage.output_tokens += result.usage.output_tokens
            
            all_keys.extend(result.keys)
    
    # Deduplicate keys by name
    seen = set()
    unique_keys = []
    for key in all_keys:
        name = key.get("name", "")
        if name and name not in seen:
            seen.add(name)
            unique_keys.append(key)
    
    print(f"\n  Total: {len(unique_keys)} unique keys extracted")
    
    # Print token usage
    if total_usage.input_tokens > 0:
        print(f"\n  Token usage:")
        print(f"    Input:  {total_usage.input_tokens:,}")
        print(f"    Output: {total_usage.output_tokens:,}")
        input_cost = total_usage.input_tokens * 3.0 / 1_000_000
        output_cost = total_usage.output_tokens * 15.0 / 1_000_000
        print(f"    Est. cost: ${input_cost + output_cost:.2f}")
    
    # Write output
    if unique_keys:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        out_file = args.out_dir / f"{pdf_path.stem}_config_keys.json"
        
        # Group keys by group name
        groups_dict = {}
        for key in unique_keys:
            name = key.get("name", "")
            parts = name.split("-")
            if len(parts) >= 2:
                group = f"{parts[0]}-{parts[1]}"
                if group not in groups_dict:
                    groups_dict[group] = {
                        "name": group,
                        "keys": []
                    }
                groups_dict[group]["keys"].append(key)
        
        output = {
            "schema_version": "1.0",
            "source_document": {"filename": pdf_path.name},
            "extraction_metadata": {
                "model": args.model,
                "groups_extracted": len(groups),
            },
            "groups": groups_dict,
            "keys": unique_keys,
            "_stats": {
                "total_keys": len(unique_keys),
                "total_groups": len(groups_dict),
            }
        }
        
        out_file.write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"\n  Wrote to: {out_file}")
    
    return len(unique_keys), unique_keys


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        return 2
    
    args = _parse_args()
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    cache_dir = script_dir / ".config_key_cache"
    
    # Handle --all-manuals mode
    if args.all_manuals:
        manuals_json = project_root / "interface_manuals" / "manuals.json"
        if not manuals_json.exists():
            print(f"Error: {manuals_json} not found")
            return 2
        
        manuals = get_unique_manuals_from_json(manuals_json)
        print(f"Found {len(manuals)} F9+ interface description manuals\n")
        
        # Check which need extraction
        to_extract = []
        for manual in manuals:
            title = manual["title"]
            output_file = args.out_dir / f"{title}_config_keys.json"
            
            if output_file.exists() and not args.force:
                print(f"  [SKIP] {title}")
            else:
                to_extract.append(manual)
                print(f"  [TODO] {title}")
        
        print(f"\n{len(to_extract)} manuals to extract")
        
        if not to_extract:
            print("\nNothing to extract. Use --force to re-extract.")
            return 0
        
        if not args.dry_run:
            response = input("Proceed with extraction? [y/N] ")
            if response.lower() != 'y':
                print("Aborted.")
                return 0
        
        cache = load_cache(cache_dir) if args.use_cache else {}
        total_keys = 0
        
        for i, manual in enumerate(to_extract, 1):
            title = manual["title"]
            local_path = project_root / manual["local_path"]
            
            print(f"\n{'='*60}")
            print(f"[{i}/{len(to_extract)}] {title}")
            print(f"{'='*60}")
            
            if not local_path.exists():
                print(f"  ERROR: PDF not found: {local_path}")
                continue
            
            try:
                count, _ = process_single_pdf(local_path, args, cache, cache_dir)
                total_keys += count
            except KeyboardInterrupt:
                print("\n\nInterrupted by user")
                break
            except Exception as e:
                print(f"  ERROR: {e}")
        
        print(f"\n{'='*60}")
        print(f"COMPLETE: {total_keys} total keys extracted")
        return 0
    
    # Single PDF mode
    if not args.pdf_path:
        print("Error: --pdf-path required (or use --all-manuals)")
        return 2
    
    if not args.pdf_path.exists():
        print(f"Error: PDF not found: {args.pdf_path}")
        return 2
    
    cache = load_cache(cache_dir) if args.use_cache else {}
    count, _ = process_single_pdf(args.pdf_path, args, cache, cache_dir)
    
    return 0 if count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
