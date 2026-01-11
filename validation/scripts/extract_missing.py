#!/usr/bin/env python3
"""
Extract missing messages from PDF manuals.

Focused extraction script for messages identified by gap analysis.
Uses a simpler single-pass approach with immediate validation.

Usage:
    uv run python validation/scripts/extract_missing.py UBX-NAV2-PVT
    uv run python validation/scripts/extract_missing.py --all
    uv run python validation/scripts/extract_missing.py --list
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

import fitz  # PyMuPDF

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from extraction.prompts import build_extraction_prompt


@dataclass
class ExtractionResult:
    """Result of extracting a message."""
    message_name: str
    manual: str
    success: bool
    extracted: dict | None = None
    error: str | None = None
    pdf_pages: tuple[int, int] | None = None


def load_gap_analysis() -> dict:
    """Load the gap analysis report."""
    report_file = PROJECT_ROOT / "validation" / "reports" / "gap_analysis.json"
    if not report_file.exists():
        print("Error: Run gap_analysis.py first")
        sys.exit(1)
    with open(report_file) as f:
        return json.load(f)


def load_inventory() -> dict:
    """Load the PDF inventory."""
    inventory_file = PROJECT_ROOT / "validation" / "inventory" / "pdf_inventory.json"
    with open(inventory_file) as f:
        return json.load(f)


def find_pdf_manuals() -> list[Path]:
    """Find all PDF manuals."""
    manuals_dir = PROJECT_ROOT / "interface_manuals"
    return sorted(manuals_dir.rglob("*.pdf"))


def discover_message_pages(pdf_path: Path, message_name: str) -> tuple[int, int] | None:
    """Find page range for a message in a PDF using TOC."""
    try:
        doc = fitz.open(pdf_path)
        toc = doc.get_toc()
        doc.close()

        message_start = None
        message_end = None

        for i, entry in enumerate(toc):
            level, title, page = entry
            if message_name in title or message_name.replace("-", " ") in title:
                message_start = page
                # Find next entry at same or higher level
                for j in range(i + 1, len(toc)):
                    next_level, _, next_page = toc[j]
                    if next_level <= level:
                        message_end = next_page - 1
                        break
                if message_end is None:
                    message_end = message_start + 3  # Default to 4 pages
                break

        if message_start:
            # Ensure minimum 2 pages
            if message_end and message_end < message_start + 1:
                message_end = message_start + 1
            return (message_start, min(message_end, message_start + 5))  # Max 6 pages
        return None

    except Exception as e:
        print(f"  Error reading TOC: {e}")
        return None


def extract_pdf_pages(pdf_path: Path, start_page: int, end_page: int) -> Path:
    """Extract specific pages from PDF to a temporary file."""
    doc = fitz.open(pdf_path)
    new_doc = fitz.open()

    # Pages are 0-indexed in fitz, but TOC gives 1-indexed
    for page_num in range(start_page - 1, min(end_page, len(doc))):
        new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)

    temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    new_doc.save(temp_file.name)
    new_doc.close()
    doc.close()

    return Path(temp_file.name)


def extract_message_from_pdf(
    message_name: str,
    pdf_path: Path,
    client,
    model: str = "gemini-2.5-flash",
) -> ExtractionResult:
    """Extract a single message definition from a PDF."""

    manual_name = pdf_path.stem

    # Find message pages
    pages = discover_message_pages(pdf_path, message_name)
    if not pages:
        return ExtractionResult(
            message_name=message_name,
            manual=manual_name,
            success=False,
            error="Message not found in TOC",
        )

    start_page, end_page = pages
    print(f"    Found on pages {start_page}-{end_page}")

    # Extract relevant pages
    temp_pdf = extract_pdf_pages(pdf_path, start_page, end_page)

    try:
        # Upload PDF to Gemini
        uploaded_file = client.files.upload(file=temp_pdf)

        # Build extraction prompt
        prompt = build_extraction_prompt(message_name)
        prompt += """

OUTPUT FORMAT:
Return ONLY a valid JSON object with this structure:
```json
{
  "name": "UBX-XXX-YYY",
  "class_id": "0x01",
  "message_id": "0x07",
  "message_type": "periodic_polled",
  "description": "Message description",
  "payload": {
    "length": {"fixed": N} or {"variable": {"base": N, "formula": "..."}},
    "fields": [
      {
        "name": "fieldName",
        "byte_offset": 0,
        "data_type": "U4",
        "description": "Field description"
      }
    ]
  }
}
```
Do NOT include any text outside the JSON. Return ONLY the JSON object.
"""

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

        extracted = json.loads(response_text)

        return ExtractionResult(
            message_name=message_name,
            manual=manual_name,
            success=True,
            extracted=extracted,
            pdf_pages=(start_page, end_page),
        )

    except json.JSONDecodeError as e:
        return ExtractionResult(
            message_name=message_name,
            manual=manual_name,
            success=False,
            error=f"JSON parse error: {e}",
            pdf_pages=(start_page, end_page),
        )
    except Exception as e:
        return ExtractionResult(
            message_name=message_name,
            manual=manual_name,
            success=False,
            error=str(e),
            pdf_pages=(start_page, end_page),
        )
    finally:
        temp_pdf.unlink(missing_ok=True)


def extract_missing_message(
    message_name: str,
    inventory: dict,
) -> dict | None:
    """
    Extract a missing message from its best manual source.

    Prefers manuals with the most messages of the same class.
    """
    from google import genai

    # Find which manuals have this message
    manuals = inventory.get("messages", {}).get(message_name, [])
    if not manuals:
        print(f"Error: {message_name} not found in any manual")
        return None

    # Prefer newer F9/F10/X20 manuals
    preferred_order = ["F9", "F10", "X20", "M10", "M9", "M8"]

    def manual_priority(name: str) -> int:
        for i, prefix in enumerate(preferred_order):
            if prefix in name:
                return i
        return len(preferred_order)

    sorted_manuals = sorted(manuals, key=manual_priority)

    # Find the PDF file for the best manual
    all_pdfs = find_pdf_manuals()
    pdf_path = None
    chosen_manual = None

    for manual_name in sorted_manuals:
        for pdf in all_pdfs:
            if pdf.stem == manual_name:
                pdf_path = pdf
                chosen_manual = manual_name
                break
        if pdf_path:
            break

    if not pdf_path:
        print(f"Error: Could not find PDF for {message_name}")
        return None

    print(f"  Extracting from: {chosen_manual}")

    # Initialize Gemini client
    client = genai.Client()

    # Extract
    result = extract_message_from_pdf(
        message_name=message_name,
        pdf_path=pdf_path,
        client=client,
    )

    if result.success:
        print(f"  Success: {len(result.extracted.get('payload', {}).get('fields', []))} fields")
        return result.extracted
    else:
        print(f"  Failed: {result.error}")
        return None


def list_missing_messages():
    """List all missing messages from gap analysis."""
    gap = load_gap_analysis()
    missing = gap.get("messages", {}).get("missing", {})

    print(f"Missing messages ({len(missing)}):\n")

    # Group by class
    by_class = {}
    for msg_name, details in missing.items():
        parts = msg_name.split("-")
        if len(parts) >= 2:
            msg_class = parts[1]
            if msg_class not in by_class:
                by_class[msg_class] = []
            by_class[msg_class].append((msg_name, details["manual_count"]))

    for msg_class, messages in sorted(by_class.items()):
        print(f"{msg_class} ({len(messages)}):")
        for msg_name, count in sorted(messages):
            print(f"  {msg_name} (in {count} manuals)")
        print()


def save_extraction(message: dict, output_dir: Path):
    """Save extracted message to file."""
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = message["name"].replace("-", "_")
    output_file = output_dir / f"{safe_name}.json"

    with open(output_file, "w") as f:
        json.dump(message, f, indent=2)

    print(f"  Saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract missing messages from PDF manuals"
    )
    parser.add_argument(
        "message",
        nargs="?",
        help="Message name to extract (e.g., UBX-NAV2-PVT)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Extract all missing messages"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List missing messages"
    )
    parser.add_argument(
        "--class",
        dest="msg_class",
        help="Extract all missing messages of a class (e.g., NAV2)"
    )

    args = parser.parse_args()

    if args.list:
        list_missing_messages()
        return 0

    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set")
        return 1

    # Load gap analysis
    gap = load_gap_analysis()
    missing = gap.get("messages", {}).get("missing", {})
    inventory = load_inventory()

    # Determine which messages to extract
    messages_to_extract = []

    if args.all:
        messages_to_extract = list(missing.keys())
    elif args.msg_class:
        messages_to_extract = [
            m for m in missing.keys()
            if m.split("-")[1] == args.msg_class
        ]
    elif args.message:
        if args.message in missing:
            messages_to_extract = [args.message]
        else:
            print(f"Error: {args.message} not in missing list")
            return 1
    else:
        parser.print_help()
        return 1

    print(f"Extracting {len(messages_to_extract)} messages...\n")

    output_dir = PROJECT_ROOT / "data" / "preliminary" / "extracted_missing"

    success_count = 0
    for msg_name in messages_to_extract:
        print(f"\n[{messages_to_extract.index(msg_name) + 1}/{len(messages_to_extract)}] {msg_name}")

        extracted = extract_missing_message(msg_name, inventory)

        if extracted:
            save_extraction(extracted, output_dir)
            success_count += 1

        # Rate limiting
        time.sleep(1)

    print(f"\n=== Summary ===")
    print(f"Extracted: {success_count}/{len(messages_to_extract)}")
    print(f"Output dir: {output_dir}")

    return 0 if success_count == len(messages_to_extract) else 1


if __name__ == "__main__":
    sys.exit(main())
