#!/usr/bin/env python3
"""
Re-extract messages with incomplete field definitions.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF
import google.generativeai as genai

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from extraction.prompts import build_extraction_prompt


def load_inventory():
    """Load PDF inventory."""
    inv_file = PROJECT_ROOT / "validation" / "inventory" / "pdf_inventory.json"
    with open(inv_file) as f:
        return json.load(f)


def find_message_pages(pdf_path: Path, msg_name: str) -> tuple[int, int] | None:
    """Find page range for a message in a PDF."""
    doc = fitz.open(pdf_path)
    toc = doc.get_toc()

    # Normalize message name for matching
    search_name = msg_name.replace("UBX-", "").replace("-", " ").upper()
    alt_search = msg_name.replace("-", " ")

    start_page = None
    end_page = None

    for i, (level, title, page) in enumerate(toc):
        title_upper = title.upper()
        if search_name in title_upper or msg_name in title:
            start_page = page
            # Find next section at same or higher level
            for j in range(i + 1, len(toc)):
                next_level, _, next_page = toc[j]
                if next_level <= level:
                    end_page = next_page - 1
                    break
            if end_page is None:
                end_page = start_page + 5
            break

    doc.close()
    return (start_page, end_page) if start_page else None


def extract_pages_as_images(pdf_path: Path, start: int, end: int) -> list:
    """Extract PDF pages as images for Gemini."""
    doc = fitz.open(pdf_path)
    images = []

    for page_num in range(start - 1, min(end, len(doc))):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom
        images.append({
            "mime_type": "image/png",
            "data": pix.tobytes("png")
        })

    doc.close()
    return images


def extract_message(msg_name: str, inventory: dict) -> dict | None:
    """Extract a single message from PDF."""
    # Find which PDFs have this message
    manuals = inventory.get("messages", {}).get(msg_name, [])
    if not manuals:
        print(f"  No PDF found for {msg_name}")
        return None

    # Prefer newer F9/M10/X20 manuals
    preferred = [m for m in manuals if any(x in m for x in ['F9', 'M10', 'X20', 'F10'])]
    manual = preferred[0] if preferred else manuals[0]

    # Find PDF file
    pdf_dir = PROJECT_ROOT / "interface_manuals"
    pdf_file = None
    for p in pdf_dir.rglob(f"{manual}.pdf"):
        pdf_file = p
        break

    if not pdf_file:
        print(f"  PDF not found: {manual}")
        return None

    # Find pages
    pages = find_message_pages(pdf_file, msg_name)
    if not pages:
        print(f"  Could not find {msg_name} in TOC")
        return None

    print(f"  Found in {manual}, pages {pages[0]}-{pages[1]}")

    # Extract images
    images = extract_pages_as_images(pdf_file, pages[0], pages[1])

    # Build prompt
    prompt = build_extraction_prompt(msg_name)

    # Call Gemini
    model = genai.GenerativeModel("gemini-2.0-flash")

    content = [prompt] + images
    response = model.generate_content(content)

    # Parse JSON response
    text = response.text
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    try:
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}")
        return None


def main():
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set")
        return 1

    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

    # Messages with incomplete fields
    incomplete = [
        "UBX-NAV-PVT",
        "UBX-CFG-TXSLOT",
        "UBX-CFG-NMEA",
        "UBX-NAV-TIMETRUSTED",
        "UBX-MGA-GPS-IONO",
        "UBX-MGA-GAL-ALM",
        "UBX-LOG-BATCH",
        "UBX-RXM-RLM-LONG",
        "UBX-MGA-GPS-EPH",
        "UBX-CFG-RXM",
    ]

    # Allow specifying specific messages
    if len(sys.argv) > 1:
        incomplete = sys.argv[1:]

    inventory = load_inventory()
    output_dir = PROJECT_ROOT / "data" / "preliminary" / "reextracted_fixes"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Re-extracting {len(incomplete)} messages with incomplete fields...\n")

    success = 0
    for msg_name in incomplete:
        print(f"Extracting {msg_name}...")

        result = extract_message(msg_name, inventory)
        if result:
            # Save
            filename = msg_name.replace("-", "_") + ".json"
            output_file = output_dir / filename
            with open(output_file, "w") as f:
                json.dump(result, f, indent=2)
            print(f"  Saved to {output_file}")
            success += 1
        else:
            print(f"  FAILED")

        time.sleep(1)  # Rate limit

    print(f"\n=== Summary ===")
    print(f"Success: {success}/{len(incomplete)}")
    print(f"Output: {output_dir}")

    return 0 if success == len(incomplete) else 1


if __name__ == "__main__":
    sys.exit(main())
