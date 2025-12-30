#!/usr/bin/env python3
"""Re-extract MON-GNSS and NAV-RELPOSNED from all manuals with fixed versioning.

These messages were previously extracted incorrectly (both V0 and V1 from every
PDF due to auto-expansion bug). This script re-extracts them with correct naming.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.extraction.extractor import call_claude_for_extraction, normalize_extraction
from src.extraction.pdf_utils import (
    extract_pages_as_images_cropped,
    find_message_locations,
)
from src.validation.grouping import parse_source_from_filename


MESSAGES_TO_EXTRACT = ["UBX-MON-GNSS", "UBX-NAV-RELPOSNED"]


def get_pdf_for_manual(project_root: Path, extraction_file: Path) -> Path | None:
    """Find the PDF corresponding to an extraction file."""
    manuals_json = project_root / "interface_manuals" / "manuals.json"
    data = json.loads(manuals_json.read_text())
    
    source = parse_source_from_filename(extraction_file.name)
    
    for module_name, module_data in data.items():
        for manual in module_data.get("manuals", []):
            local_path = project_root / manual.get("local_path", "")
            if local_path.exists():
                pdf_source = parse_source_from_filename(local_path.name)
                if pdf_source.short_name == source.short_name:
                    return local_path
    return None


def extract_message(
    pdf_path: Path,
    message_name: str,
    model: str = "claude-sonnet-4-20250514",
    max_pages: int = 3,
) -> dict | None:
    """Extract a single message from a PDF."""
    
    locations = find_message_locations(pdf_path, [message_name])
    if message_name not in locations:
        return None
    
    loc = locations[message_name]
    page_end = min(loc.page_end, loc.page_start + max_pages)
    
    images = extract_pages_as_images_cropped(
        pdf_path,
        loc.page_start,
        page_end,
        crop_top_ratio=0.095,
        crop_bottom_ratio=0.085,
    )
    
    print(f"      Calling Claude ({len(images)} pages)...")
    
    raw, usage = call_claude_for_extraction(
        images=images,
        message_name=message_name,
        expected_class_id=loc.class_id or None,
        expected_message_id=loc.message_id or None,
        model=model,
        max_tokens=8192,
    )
    
    result = normalize_extraction(raw, message_name, "reextract")
    
    if result.success:
        return result.message
    else:
        print(f"      ERROR: {result.errors}")
        return None


def add_message_to_file(extraction_file: Path, message: dict) -> None:
    """Add a message to an extraction file."""
    data = json.loads(extraction_file.read_text())
    data["messages"].append(message)
    extraction_file.write_text(json.dumps(data, indent=2))


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        return 2
    
    project_root = Path(__file__).parent.parent
    extractions_dir = project_root / "data" / "by-manual"
    
    extraction_files = sorted(extractions_dir.glob("*_anthropic.json"))
    
    # Count total extractions needed
    total = len(extraction_files) * len(MESSAGES_TO_EXTRACT)
    estimated_cost = total * 0.30
    
    print(f"Will extract {len(MESSAGES_TO_EXTRACT)} messages from {len(extraction_files)} manuals")
    print(f"Total extractions: {total}")
    print(f"Estimated cost: ~${estimated_cost:.2f}")
    
    response = input("Proceed? [y/N] ")
    if response.lower() != 'y':
        print("Aborted.")
        return 0
    
    success = 0
    failed = []
    
    for i, extraction_file in enumerate(extraction_files, 1):
        source = parse_source_from_filename(extraction_file.name)
        pdf_path = get_pdf_for_manual(project_root, extraction_file)
        
        if not pdf_path:
            print(f"[{i}/{len(extraction_files)}] {source.short_name}: PDF not found")
            continue
        
        print(f"[{i}/{len(extraction_files)}] {source.short_name}")
        
        for msg_name in MESSAGES_TO_EXTRACT:
            print(f"    Extracting {msg_name}...")
            
            try:
                result = extract_message(pdf_path, msg_name)
                
                if result:
                    add_message_to_file(extraction_file, result)
                    extracted_name = result.get('name', msg_name)
                    print(f"      ✅ Added as {extracted_name}")
                    success += 1
                else:
                    print(f"      ⚠️  Not found in PDF")
                    
            except KeyboardInterrupt:
                print("\n\nInterrupted")
                return 1
            except Exception as e:
                print(f"      ❌ Error: {e}")
                failed.append(f"{msg_name}@{source.short_name}")
    
    print(f"\n{'='*60}")
    print(f"Complete: {success} extractions successful")
    
    if failed:
        print(f"Failed ({len(failed)}):")
        for f in failed[:10]:
            print(f"  - {f}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
