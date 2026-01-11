#!/usr/bin/env python3
"""
Validate UBX configuration key definitions against PDF manuals.

Config keys are validated by group (e.g., CFG-RATE, CFG-NAVSPG) since they
appear together in the PDFs.

Usage:
    uv run python validation/scripts/validate_config_keys.py CFG-RATE
    uv run python validation/scripts/validate_config_keys.py CFG-RATE --manual F9-HPG-1.51
    uv run python validation/scripts/validate_config_keys.py --list-groups
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "validation"))

from prompts.ubx_knowledge import build_config_key_validation_prompt
from validation.scripts.validate_message import (
    ManualMetadata,
    load_manual_metadata,
    find_pdf_manuals,
    extract_pdf_pages,
)


@dataclass
class ConfigKeyValidationResult:
    """Result of validating config keys against a manual."""
    manual: str
    group: str
    keys_checked: int
    matches: bool | None
    confidence: str
    discrepancies: list[dict]
    notes: str
    pdf_pages: tuple[int, int] | None = None
    protocol_version: int | None = None
    device_family: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> dict:
        return {
            "manual": self.manual,
            "group": self.group,
            "keys_checked": self.keys_checked,
            "matches": self.matches,
            "confidence": self.confidence,
            "discrepancies": self.discrepancies,
            "notes": self.notes,
            "pdf_pages": self.pdf_pages,
            "protocol_version": self.protocol_version,
            "device_family": self.device_family,
            "timestamp": self.timestamp,
        }


def load_config_keys() -> dict:
    """Load config key definitions."""
    keys_file = PROJECT_ROOT / "data" / "config_keys" / "unified_config_keys.json"
    with open(keys_file) as f:
        return json.load(f)


def get_keys_by_group(config_data: dict) -> dict[str, list[dict]]:
    """Group config keys by their group name."""
    by_group = {}
    for key in config_data.get("keys", []):
        group = key.get("group", "unknown")
        if group not in by_group:
            by_group[group] = []
        by_group[group].append(key)
    return by_group


def discover_config_key_pages(pdf_path: Path, group_name: str) -> tuple[int, int] | None:
    """Find page range for a config key group in a PDF using TOC."""
    try:
        doc = fitz.open(pdf_path)
        toc = doc.get_toc()
        doc.close()
        
        # Config keys are usually in "Configuration" section
        # Look for the group name (e.g., "CFG-RATE" or "Configuration keys")
        group_start = None
        group_end = None
        
        # Search patterns
        search_terms = [
            group_name,
            group_name.replace("-", " "),
            f"Configuration: {group_name}",
        ]
        
        for i, entry in enumerate(toc):
            level, title, page = entry
            
            # Check if this entry matches our group
            if any(term.lower() in title.lower() for term in search_terms):
                group_start = page
                # Find next entry at same or higher level
                for j in range(i + 1, len(toc)):
                    next_level, _, next_page = toc[j]
                    if next_level <= level:
                        group_end = next_page - 1
                        break
                if group_end is None:
                    group_end = group_start + 2
                break
        
        if group_start:
            # Ensure minimum 2 pages (content often spans header page + payload page)
            if group_end and group_end < group_start + 1:
                group_end = group_start + 1
            return (group_start, min(group_end, group_start + 5))  # Max 6 pages
        return None
        
    except Exception:
        return None


def validate_config_keys_against_manual(
    group_name: str,
    keys: list[dict],
    pdf_path: Path,
    client: Any,
    metadata: ManualMetadata | None = None,
    model: str = "gemini-2.5-flash",
    verbose: bool = False,
) -> ConfigKeyValidationResult:
    """Validate config keys against a PDF manual."""
    
    manual_name = pdf_path.stem
    
    # Find config key pages in PDF
    pages = discover_config_key_pages(pdf_path, group_name)
    if not pages:
        return ConfigKeyValidationResult(
            manual=manual_name,
            group=group_name,
            keys_checked=len(keys),
            matches=None,
            confidence="high",
            discrepancies=[],
            notes=f"Config key group {group_name} not found in TOC",
            protocol_version=metadata.protocol_version if metadata else None,
            device_family=metadata.device_family if metadata else None,
        )
    
    start_page, end_page = pages
    if verbose:
        print(f"  Found {group_name} on pages {start_page}-{end_page}")
    
    # Extract relevant pages
    temp_pdf = extract_pdf_pages(pdf_path, start_page, end_page)
    
    try:
        # Upload PDF to Gemini
        uploaded_file = client.files.upload(file=temp_pdf)
        
        # Build validation prompt
        keys_json = json.dumps(keys, indent=2)
        prompt = build_config_key_validation_prompt(keys_json)
        
        # Call LLM
        response = client.models.generate_content(
            model=model,
            contents=[
                uploaded_file,
                prompt,
            ],
        )
        
        # Parse response
        response_text = response.text.strip()
        
        # Extract JSON from response
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()
        elif "```" in response_text:
            json_start = response_text.find("```") + 3
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()
        
        result_data = json.loads(response_text)
        
        return ConfigKeyValidationResult(
            manual=manual_name,
            group=group_name,
            keys_checked=len(keys),
            matches=result_data.get("matches"),
            confidence=result_data.get("confidence", "medium"),
            discrepancies=result_data.get("discrepancies", []),
            notes=result_data.get("notes", ""),
            pdf_pages=(start_page, end_page),
            protocol_version=metadata.protocol_version if metadata else None,
            device_family=metadata.device_family if metadata else None,
        )
        
    except json.JSONDecodeError as e:
        return ConfigKeyValidationResult(
            manual=manual_name,
            group=group_name,
            keys_checked=len(keys),
            matches=None,
            confidence="low",
            discrepancies=[],
            notes=f"Failed to parse LLM response: {e}",
            pdf_pages=(start_page, end_page),
            protocol_version=metadata.protocol_version if metadata else None,
            device_family=metadata.device_family if metadata else None,
        )
    except Exception as e:
        return ConfigKeyValidationResult(
            manual=manual_name,
            group=group_name,
            keys_checked=len(keys),
            matches=None,
            confidence="low",
            discrepancies=[],
            notes=f"Validation error: {e}",
            pdf_pages=(start_page, end_page),
            protocol_version=metadata.protocol_version if metadata else None,
            device_family=metadata.device_family if metadata else None,
        )
    finally:
        temp_pdf.unlink(missing_ok=True)


def validate_config_key_group(
    group_name: str,
    manuals: list[Path] | None = None,
    verbose: bool = False,
) -> list[ConfigKeyValidationResult]:
    """Validate a config key group against all (or specified) manuals."""
    
    from google import genai
    
    # Load config keys
    config_data = load_config_keys()
    keys_by_group = get_keys_by_group(config_data)
    
    if group_name not in keys_by_group:
        print(f"Error: Config key group '{group_name}' not found")
        print(f"Available groups: {sorted(keys_by_group.keys())[:10]}...")
        return []
    
    keys = keys_by_group[group_name]
    
    # Get manuals (only F9+ have CFG-VAL* keys)
    if manuals is None:
        manuals = find_pdf_manuals()
    
    if not manuals:
        print("Error: No PDF manuals found")
        return []
    
    # Load manual metadata
    all_metadata = load_manual_metadata()
    
    # Initialize Gemini client
    client = genai.Client()
    
    results = []
    found_count = 0
    match_count = 0
    mismatch_count = 0
    
    print(f"Validating {group_name} ({len(keys)} keys) against {len(manuals)} manuals...")
    
    for pdf_path in manuals:
        manual_name = pdf_path.stem
        metadata = all_metadata.get(manual_name)
        
        # Skip M8 manuals for config keys (they don't have CFG-VAL*)
        if metadata and metadata.device_family == "M8":
            if verbose:
                print(f"  Skipping {manual_name[:40]}: M8 doesn't support CFG-VAL*")
            continue
        
        if verbose:
            version_info = f" (protocol {metadata.protocol_version_str})" if metadata else ""
            print(f"\nChecking {manual_name}{version_info}...")
        
        result = validate_config_keys_against_manual(
            group_name=group_name,
            keys=keys,
            pdf_path=pdf_path,
            client=client,
            metadata=metadata,
            verbose=verbose,
        )
        results.append(result)
        
        if result.matches is None:
            status = "- not found"
        elif result.matches:
            status = "✓ matches"
            found_count += 1
            match_count += 1
        else:
            status = f"✗ {len(result.discrepancies)} discrepancies"
            found_count += 1
            mismatch_count += 1
        
        print(f"  {manual_name[:40]}: {status}")
        
        # Rate limiting
        time.sleep(0.5)
    
    # Summary
    print(f"\n=== Summary ===")
    print(f"  Found in {found_count}/{len(results)} manuals")
    print(f"  Matches: {match_count}")
    print(f"  Mismatches: {mismatch_count}")
    
    return results


def save_results(group_name: str, results: list[ConfigKeyValidationResult]):
    """Save validation results."""
    reports_dir = PROJECT_ROOT / "validation" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    safe_name = group_name.replace("-", "_")
    results_file = reports_dir / f"{safe_name}_validation.json"
    
    with open(results_file, "w") as f:
        json.dump({
            "group": group_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": [r.to_dict() for r in results],
            "summary": {
                "total_manuals": len(results),
                "found_in": sum(1 for r in results if r.matches is not None),
                "matches": sum(1 for r in results if r.matches is True),
                "mismatches": sum(1 for r in results if r.matches is False),
            }
        }, f, indent=2)
    
    print(f"Results saved to: {results_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Validate UBX config keys against PDF manuals"
    )
    parser.add_argument(
        "group",
        nargs="?",
        help="Config key group name (e.g., CFG-RATE)"
    )
    parser.add_argument(
        "--list-groups",
        action="store_true",
        help="List available config key groups"
    )
    parser.add_argument(
        "--manual",
        help="Specific manual to check (substring match)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save results to file"
    )
    
    args = parser.parse_args()
    
    # List groups mode
    if args.list_groups:
        config_data = load_config_keys()
        keys_by_group = get_keys_by_group(config_data)
        print(f"Available config key groups ({len(keys_by_group)}):")
        for group, keys in sorted(keys_by_group.items()):
            print(f"  {group}: {len(keys)} keys")
        return 0
    
    if not args.group:
        parser.print_help()
        return 1
    
    # Check API key
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set")
        return 1
    
    # Filter manuals if specified
    manuals = None
    if args.manual:
        all_manuals = find_pdf_manuals()
        manuals = [m for m in all_manuals if args.manual.lower() in m.stem.lower()]
        if not manuals:
            print(f"Error: No manuals matching '{args.manual}'")
            return 1
    
    # Run validation
    results = validate_config_key_group(
        group_name=args.group,
        manuals=manuals,
        verbose=args.verbose,
    )
    
    if not results:
        return 1
    
    # Save results
    if not args.no_save:
        save_results(args.group, results)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
