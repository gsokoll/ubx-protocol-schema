#!/usr/bin/env python3
"""
Validate UBX configuration key definitions against PDF manuals.

Config keys are validated by group (e.g., CFG-RATE, CFG-NAVSPG) since they
appear together in the PDFs.

Usage:
    # Validate config keys against manuals
    uv run python validation/scripts/validate_config_keys.py CFG-RATE
    uv run python validation/scripts/validate_config_keys.py CFG-RATE --manual F9-HPG-1.51
    uv run python validation/scripts/validate_config_keys.py --list-groups

    # Extract missing enum values (fix incomplete extractions)
    uv run python validation/scripts/validate_config_keys.py CFG-NAVSPG --manual LAP-1.50 --extract-missing --dry-run
    uv run python validation/scripts/validate_config_keys.py CFG-NAVSPG --manual LAP-1.50 --extract-missing --apply
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

from prompts.ubx_knowledge import build_config_key_validation_prompt, build_enum_extraction_prompt
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


# ============================================================================
# Enum Extraction Functions (--extract-missing --apply workflow)
# ============================================================================

def get_by_manual_file(manual_pattern: str) -> Path | None:
    """Find a by-manual extraction file matching the pattern."""
    by_manual_dir = PROJECT_ROOT / "data" / "config_keys" / "by-manual"
    for f in by_manual_dir.glob("*_gemini_config_keys.json"):
        if manual_pattern.lower() in f.stem.lower():
            return f
    return None


def get_pdf_for_manual(manual_file: Path) -> Path | None:
    """Find the PDF corresponding to a by-manual extraction file."""
    # Extract the manual name from the extraction filename
    # e.g., "u-blox-F9-LAP-1.50_InterfaceDescription_UBXDOC-963802114-13052_gemini_config_keys.json"
    # -> "u-blox-F9-LAP-1.50_InterfaceDescription_UBXDOC-963802114-13052.pdf"
    manual_name = manual_file.stem.replace("_gemini_config_keys", "")

    # Search in interface_manuals subdirectories
    for pdf in (PROJECT_ROOT / "interface_manuals").rglob("*.pdf"):
        if manual_name in pdf.stem or pdf.stem in manual_name:
            return pdf
    return None


def load_by_manual_keys(manual_file: Path) -> dict:
    """Load config keys from a by-manual extraction file."""
    with open(manual_file) as f:
        return json.load(f)


def find_incomplete_enums(
    manual_file: Path,
    group_name: str,
    reference_file: Path | None = None,
) -> list[dict]:
    """Find E-type keys with potentially incomplete inline_enum in a by-manual file.

    Args:
        manual_file: Path to the by-manual extraction file
        group_name: Config key group to check (e.g., "CFG-NAVSPG")
        reference_file: Optional reference file with known-good enums

    Returns:
        List of dicts with key info and missing values
    """
    data = load_by_manual_keys(manual_file)
    groups = data.get("groups", {})

    if group_name not in groups:
        return []

    group = groups[group_name]
    keys = group.get("keys", [])

    # Load reference if provided
    reference_enums = {}
    if reference_file:
        ref_data = load_by_manual_keys(reference_file)
        ref_groups = ref_data.get("groups", {})
        if group_name in ref_groups:
            for key in ref_groups[group_name].get("keys", []):
                if key.get("data_type", "").startswith("E"):
                    enum_values = key.get("inline_enum", {}).get("values", {})
                    if enum_values:
                        reference_enums[key["name"]] = enum_values

    incomplete = []
    for key in keys:
        data_type = key.get("data_type", "")
        if not data_type.startswith("E"):
            continue

        key_name = key["name"]
        current_values = key.get("inline_enum", {}).get("values", {})

        # Check if this enum has fewer values than reference
        if key_name in reference_enums:
            ref_values = reference_enums[key_name]
            missing = set(ref_values.keys()) - set(current_values.keys())
            if missing:
                incomplete.append({
                    "key_name": key_name,
                    "data_type": data_type,
                    "current_count": len(current_values),
                    "reference_count": len(ref_values),
                    "current_values": list(current_values.keys()),
                    "missing_values": list(missing),
                })
        elif len(current_values) <= 1:
            # No reference, but suspiciously few values
            incomplete.append({
                "key_name": key_name,
                "data_type": data_type,
                "current_count": len(current_values),
                "reference_count": None,
                "current_values": list(current_values.keys()),
                "missing_values": [],
                "note": "Only 1 or fewer enum values - likely incomplete",
            })

    return incomplete


def extract_enum_from_pdf(
    key_name: str,
    data_type: str,
    pdf_path: Path,
    client: any,
    model: str = "gemini-2.5-flash",
    verbose: bool = False,
) -> dict | None:
    """Extract complete enum definition for a config key from PDF.

    Args:
        key_name: Config key name (e.g., "CFG-NAVSPG-DYNMODEL")
        data_type: Data type (E1, E2, E4)
        pdf_path: Path to PDF manual
        client: Gemini client
        model: Model to use
        verbose: Show progress

    Returns:
        Dict with extracted enum values, or None if not found
    """
    # Get the group name from key name
    parts = key_name.split("-")
    if len(parts) >= 2:
        group_name = f"{parts[0]}-{parts[1]}"
    else:
        group_name = key_name

    # Find config key pages
    pages = discover_config_key_pages(pdf_path, group_name)
    if not pages:
        if verbose:
            print(f"  Config key group {group_name} not found in TOC")
        return None

    start_page, end_page = pages
    if verbose:
        print(f"  Found {group_name} on pages {start_page}-{end_page}")

    # Extract relevant pages
    temp_pdf = extract_pdf_pages(pdf_path, start_page, end_page)

    try:
        # Upload PDF to Gemini
        uploaded_file = client.files.upload(file=temp_pdf)

        # Build extraction prompt
        prompt = build_enum_extraction_prompt(key_name, data_type)

        # Call LLM
        response = client.models.generate_content(
            model=model,
            contents=[uploaded_file, prompt],
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

        result = json.loads(response_text)

        if "error" in result:
            if verbose:
                print(f"  Extraction error: {result.get('notes', 'unknown')}")
            return None

        return result

    except json.JSONDecodeError as e:
        if verbose:
            print(f"  Failed to parse LLM response: {e}")
        return None
    except Exception as e:
        if verbose:
            print(f"  Extraction error: {e}")
        return None
    finally:
        temp_pdf.unlink(missing_ok=True)


def apply_extracted_enum(
    manual_file: Path,
    group_name: str,
    key_name: str,
    enum_values: dict,
    dry_run: bool = False,
) -> bool:
    """Update a by-manual extraction file with extracted enum values.

    Args:
        manual_file: Path to the by-manual extraction file
        group_name: Config key group (e.g., "CFG-NAVSPG")
        key_name: Config key name (e.g., "CFG-NAVSPG-DYNMODEL")
        enum_values: Dict of {NAME: {value: int, description: str}}
        dry_run: If True, show what would change without applying

    Returns:
        True if changes were made (or would be made in dry_run)
    """
    data = load_by_manual_keys(manual_file)
    groups = data.get("groups", {})

    if group_name not in groups:
        print(f"  Group {group_name} not found in {manual_file.name}")
        return False

    # Find the key
    keys = groups[group_name].get("keys", [])
    key_found = False
    for key in keys:
        if key["name"] == key_name:
            key_found = True
            old_values = key.get("inline_enum", {}).get("values", {})

            # Show diff
            new_names = set(enum_values.keys())
            old_names = set(old_values.keys())
            added = new_names - old_names

            if not added:
                print(f"  No new enum values to add for {key_name}")
                return False

            print(f"  {key_name}: Adding {len(added)} enum values:")
            for name in sorted(added):
                val = enum_values[name]
                print(f"    + {name} = {val['value']}: {val.get('description', '')[:50]}")

            if dry_run:
                print(f"  [DRY RUN] Would update {manual_file.name}")
                return True

            # Apply changes
            if "inline_enum" not in key:
                key["inline_enum"] = {"values": {}}
            key["inline_enum"]["values"] = enum_values
            break

    if not key_found:
        print(f"  Key {key_name} not found in group {group_name}")
        return False

    if not dry_run:
        # Save updated file
        with open(manual_file, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  Updated {manual_file.name}")

    return True


def extract_missing_enums(
    group_name: str,
    manual_pattern: str | None = None,
    apply: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """Extract missing enum values for a config key group.

    Args:
        group_name: Config key group (e.g., "CFG-NAVSPG")
        manual_pattern: Substring to match manual filename (e.g., "LAP-1.50")
        apply: If True, apply extracted enums to by-manual files
        dry_run: If True, show what would change without applying
        verbose: Show detailed progress

    Returns:
        Dict with extraction results and statistics
    """
    from google import genai

    # Find the manual file to fix
    if manual_pattern:
        manual_file = get_by_manual_file(manual_pattern)
        if not manual_file:
            print(f"Error: No by-manual file matching '{manual_pattern}'")
            return {"error": "manual_not_found"}
    else:
        print("Error: --manual is required for --extract-missing")
        return {"error": "manual_required"}

    print(f"Checking {manual_file.name} for incomplete enums in {group_name}...")

    # Find a good reference file (F9-HPG-1.51 is usually most complete)
    reference_file = None
    for pattern in ["F9-HPG-1.51", "F9-HPG-1.50", "F9-HPS-1.40", "X20-HPG"]:
        ref = get_by_manual_file(pattern)
        if ref and ref != manual_file:
            reference_file = ref
            if verbose:
                print(f"Using {ref.name} as reference")
            break

    # Find incomplete enums
    incomplete = find_incomplete_enums(manual_file, group_name, reference_file)

    if not incomplete:
        print(f"No incomplete enums found in {group_name}")
        return {"group": group_name, "incomplete": 0, "extracted": 0}

    print(f"Found {len(incomplete)} potentially incomplete enums:")
    for info in incomplete:
        missing_str = f", missing: {info['missing_values']}" if info.get("missing_values") else ""
        print(f"  - {info['key_name']}: {info['current_count']} values{missing_str}")

    # Find corresponding PDF
    pdf_path = get_pdf_for_manual(manual_file)
    if not pdf_path:
        print(f"Error: Could not find PDF for {manual_file.name}")
        return {"error": "pdf_not_found"}

    if verbose:
        print(f"Using PDF: {pdf_path.name}")

    # Initialize Gemini client
    client = genai.Client()

    # Extract each incomplete enum
    extracted = {}
    for info in incomplete:
        key_name = info["key_name"]
        data_type = info["data_type"]

        print(f"\nExtracting {key_name}...")

        result = extract_enum_from_pdf(
            key_name=key_name,
            data_type=data_type,
            pdf_path=pdf_path,
            client=client,
            verbose=verbose,
        )

        if result and "values" in result:
            confidence = result.get("extraction_confidence", "unknown")
            num_values = len(result["values"])
            print(f"  ✓ Extracted {num_values} enum values (confidence: {confidence})")
            extracted[key_name] = result

            # Apply if requested
            if apply or dry_run:
                apply_extracted_enum(
                    manual_file=manual_file,
                    group_name=group_name,
                    key_name=key_name,
                    enum_values=result["values"],
                    dry_run=dry_run,
                )
        else:
            print(f"  ✗ Could not extract enum values")

        # Rate limiting
        time.sleep(0.5)

    # Summary
    print(f"\n=== Summary ===")
    print(f"  Incomplete enums found: {len(incomplete)}")
    print(f"  Successfully extracted: {len(extracted)}")
    if apply and not dry_run:
        print(f"  Applied to: {manual_file.name}")
        print(f"\n  Next step: Run 'uv run python scripts/merge_config_keys.py' to update unified database")

    return {
        "group": group_name,
        "manual": manual_file.name,
        "incomplete": len(incomplete),
        "extracted": len(extracted),
        "keys": extracted,
    }


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
    parser.add_argument(
        "--extract-missing",
        action="store_true",
        help="Extract missing enum values from PDF"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply extracted enum values to by-manual files"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without applying"
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

    # Extract missing enums mode
    if args.extract_missing:
        result = extract_missing_enums(
            group_name=args.group,
            manual_pattern=args.manual,
            apply=args.apply,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
        if "error" in result:
            return 1
        return 0

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
