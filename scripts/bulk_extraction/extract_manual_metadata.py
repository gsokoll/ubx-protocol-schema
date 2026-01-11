#!/usr/bin/env python3
"""Extract firmware and protocol version metadata from all u-blox interface manuals.

This script scans all PDF manuals and extracts the firmware/protocol version
mapping table from their front matter, saving results to data/manual_metadata.json.

Usage:
    uv run python scripts/extract_manual_metadata.py
    
Output:
    data/manual_metadata.json - Metadata for all successfully processed manuals
"""

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path for src imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.extraction.pdf_utils import extract_manual_metadata


def find_all_interface_manuals(base_dir: Path) -> list[Path]:
    """Find all PDF interface description manuals (excluding PCN documents)."""
    pdfs = []
    for pdf_path in base_dir.rglob("*.pdf"):
        # Skip PCN (Product Change Notification) documents
        if "_PCN_" in pdf_path.name:
            continue
        # Skip non-interface documents
        if "InterfaceDescription" in pdf_path.name or "Interfacedescription" in pdf_path.name or "ProtSpec" in pdf_path.name:
            pdfs.append(pdf_path)
    return sorted(pdfs)


def protocol_version_to_int(version_str: str) -> int:
    """Convert protocol version string to integer (version * 100).
    
    Examples:
        "27.50" -> 2750
        "18.00" -> 1800
        "33.00" -> 3300
    """
    try:
        return int(float(version_str) * 100)
    except (ValueError, TypeError):
        return 0


def main():
    base_dir = Path(__file__).parent.parent / "interface_manuals"
    output_file = Path(__file__).parent.parent / "data" / "manual_metadata.json"
    
    print("Extracting firmware/protocol version metadata from interface manuals...")
    print(f"Scanning: {base_dir}")
    print()
    
    pdfs = find_all_interface_manuals(base_dir)
    print(f"Found {len(pdfs)} interface description manuals\n")
    
    metadata_dict = {}
    successful = 0
    failed = 0
    
    for pdf_path in pdfs:
        # Use filename without extension as key
        manual_key = pdf_path.stem
        
        metadata = extract_manual_metadata(pdf_path)
        
        if metadata.protocol_version:
            protver_int = protocol_version_to_int(metadata.protocol_version)
            print(f"✓ {pdf_path.name}")
            print(f"    Firmware: {metadata.firmware_version}, Protocol: {metadata.protocol_version} ({protver_int})")
            
            metadata_dict[manual_key] = {
                "firmware_version": metadata.firmware_version,
                "protocol_version_str": metadata.protocol_version,
                "protocol_version": protver_int,
                "version_identifier": metadata.version_identifier,
                "extraction_method": metadata.extraction_method,
                "source_file": pdf_path.name,
            }
            successful += 1
        else:
            print(f"✗ {pdf_path.name} - No metadata found")
            failed += 1
    
    # Add extraction timestamp
    output_data = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "total_manuals": len(pdfs),
        "successful": successful,
        "failed": failed,
        "manuals": metadata_dict,
    }
    
    # Save to file
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\n{'=' * 60}")
    print(f"SUMMARY")
    print(f"{'=' * 60}")
    print(f"Successful: {successful}/{len(pdfs)}")
    print(f"Failed:     {failed}/{len(pdfs)}")
    print(f"\nOutput saved to: {output_file}")


if __name__ == "__main__":
    main()
