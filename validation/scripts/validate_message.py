#!/usr/bin/env python3
"""
Validate a UBX message definition against PDF manuals.

Usage:
    uv run python validation/scripts/validate_message.py UBX-NAV-PVT
    uv run python validation/scripts/validate_message.py UBX-NAV-PVT --manual zed-f9p
    uv run python validation/scripts/validate_message.py UBX-NAV-PVT --verbose
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

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "validation"))

from prompts.ubx_knowledge import build_message_validation_prompt


@dataclass
class ManualMetadata:
    """Metadata about a PDF manual."""
    name: str
    firmware_version: str | None = None
    protocol_version: int | None = None  # e.g., 2700 for 27.00
    protocol_version_str: str | None = None
    device_family: str | None = None  # M8, F9, M10, etc.
    
    @classmethod
    def from_dict(cls, name: str, data: dict) -> "ManualMetadata":
        # Infer device family from firmware version or name
        fw = data.get("firmware_version", "")
        family = None
        if "M8" in name or "u-blox8" in name:
            family = "M8"
        elif "F9" in name or "F10" in name:
            family = "F9" if "F9" in name else "F10"
        elif "M9" in name:
            family = "M9"
        elif "M10" in name:
            family = "M10"
        elif "X20" in name or "F20" in name:
            family = "F10"  # X20/F20 are F10 generation
        
        return cls(
            name=name,
            firmware_version=data.get("firmware_version"),
            protocol_version=data.get("protocol_version"),
            protocol_version_str=data.get("protocol_version_str"),
            device_family=family,
        )


@dataclass
class ValidationResult:
    """Result of validating a message against a manual."""
    manual: str
    message: str
    matches: bool | None  # None = message not in manual
    confidence: str
    discrepancies: list[dict]
    notes: str
    pdf_pages: tuple[int, int] | None = None
    # Manual metadata for version context
    protocol_version: int | None = None
    device_family: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> dict:
        return {
            "manual": self.manual,
            "message": self.message,
            "matches": self.matches,
            "confidence": self.confidence,
            "discrepancies": self.discrepancies,
            "notes": self.notes,
            "pdf_pages": self.pdf_pages,
            "protocol_version": self.protocol_version,
            "device_family": self.device_family,
            "timestamp": self.timestamp,
        }


def load_canonical_messages() -> dict[str, dict]:
    """Load canonical message definitions."""
    msgs_file = PROJECT_ROOT / "data" / "messages" / "ubx_messages.json"
    with open(msgs_file) as f:
        data = json.load(f)
    return {m["name"]: m for m in data.get("messages", [])}


def load_manual_metadata() -> dict[str, ManualMetadata]:
    """Load manual metadata with version information."""
    meta_file = PROJECT_ROOT / "data" / "manual_metadata.json"
    if meta_file.exists():
        with open(meta_file) as f:
            data = json.load(f)
        manuals = data.get("manuals", {})
        return {
            name: ManualMetadata.from_dict(name, info)
            for name, info in manuals.items()
        }
    return {}


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
        
        # Find message in TOC
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
                    message_end = message_start + 2  # Default to 3 pages
                break
        
        if message_start:
            # Ensure minimum 2 pages (content often spans header page + payload page)
            if message_end and message_end < message_start + 1:
                message_end = message_start + 1
            return (message_start, min(message_end, message_start + 4))  # Max 5 pages
        return None
        
    except Exception:
        return None


def extract_pdf_pages(pdf_path: Path, start_page: int, end_page: int) -> Path:
    """Extract specific pages from PDF to a temporary file."""
    doc = fitz.open(pdf_path)
    new_doc = fitz.open()
    
    # Pages are 0-indexed in fitz, but TOC gives 1-indexed
    for page_num in range(start_page - 1, min(end_page, len(doc))):
        new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
    
    # Save to temp file
    temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    new_doc.save(temp_file.name)
    new_doc.close()
    doc.close()
    
    return Path(temp_file.name)


def validate_message_against_manual(
    message: dict,
    pdf_path: Path,
    client: Any,
    metadata: ManualMetadata | None = None,
    model: str = "gemini-2.5-flash",
    verbose: bool = False,
) -> ValidationResult:
    """Validate a message definition against a PDF manual."""
    
    manual_name = pdf_path.stem
    message_name = message["name"]
    
    # Get metadata for this manual
    if metadata is None:
        all_metadata = load_manual_metadata()
        metadata = all_metadata.get(manual_name)
    
    # Find message pages in PDF
    pages = discover_message_pages(pdf_path, message_name)
    if not pages:
        return ValidationResult(
            manual=manual_name,
            message=message_name,
            matches=None,
            confidence="high",
            discrepancies=[],
            notes="Message not found in TOC",
            protocol_version=metadata.protocol_version if metadata else None,
            device_family=metadata.device_family if metadata else None,
        )
    
    start_page, end_page = pages
    if verbose:
        print(f"  Found {message_name} on pages {start_page}-{end_page}")
    
    # Extract relevant pages
    temp_pdf = extract_pdf_pages(pdf_path, start_page, end_page)
    
    try:
        # Upload PDF to Gemini
        uploaded_file = client.files.upload(file=temp_pdf)
        
        # Build validation prompt with version context
        canonical_json = json.dumps(message, indent=2)
        prompt = build_message_validation_prompt(
            canonical_json=canonical_json,
            device_family=metadata.device_family if metadata else None,
            protocol_version=metadata.protocol_version if metadata else None,
            firmware_version=metadata.firmware_version if metadata else None,
        )
        
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
        
        return ValidationResult(
            manual=manual_name,
            message=message_name,
            matches=result_data.get("matches"),
            confidence=result_data.get("confidence", "medium"),
            discrepancies=result_data.get("discrepancies", []),
            notes=result_data.get("notes", ""),
            pdf_pages=(start_page, end_page),
            protocol_version=metadata.protocol_version if metadata else None,
            device_family=metadata.device_family if metadata else None,
        )
        
    except json.JSONDecodeError as e:
        return ValidationResult(
            manual=manual_name,
            message=message_name,
            matches=None,
            confidence="low",
            discrepancies=[],
            notes=f"Failed to parse LLM response: {e}",
            pdf_pages=(start_page, end_page),
            protocol_version=metadata.protocol_version if metadata else None,
            device_family=metadata.device_family if metadata else None,
        )
    except Exception as e:
        return ValidationResult(
            manual=manual_name,
            message=message_name,
            matches=None,
            confidence="low",
            discrepancies=[],
            notes=f"Validation error: {e}",
            pdf_pages=(start_page, end_page),
            protocol_version=metadata.protocol_version if metadata else None,
            device_family=metadata.device_family if metadata else None,
        )
    finally:
        # Cleanup temp file
        temp_pdf.unlink(missing_ok=True)


def validate_message(
    message_name: str,
    manuals: list[Path] | None = None,
    verbose: bool = False,
    quiet: bool = False,
) -> list[ValidationResult]:
    """Validate a message against all (or specified) manuals.
    
    Args:
        message_name: Name of message to validate
        manuals: List of PDF paths (None = all manuals)
        verbose: Show detailed progress
        quiet: Suppress all output (for parallel processing)
    """
    
    from google import genai
    
    # Load canonical message
    canonical_messages = load_canonical_messages()
    if message_name not in canonical_messages:
        if not quiet:
            print(f"Error: Message '{message_name}' not found in canonical dataset")
        return []
    
    message = canonical_messages[message_name]
    
    # Get manuals
    if manuals is None:
        manuals = find_pdf_manuals()
    
    if not manuals:
        if not quiet:
            print("Error: No PDF manuals found")
        return []
    
    # Load manual metadata for version context
    all_metadata = load_manual_metadata()
    
    # Initialize Gemini client
    client = genai.Client()
    
    results = []
    found_count = 0
    match_count = 0
    mismatch_count = 0
    
    if not quiet:
        print(f"Validating {message_name} against {len(manuals)} manuals...")
    
    for pdf_path in manuals:
        manual_name = pdf_path.stem
        metadata = all_metadata.get(manual_name)
        
        if verbose:
            version_info = f" (protocol {metadata.protocol_version_str})" if metadata else ""
            print(f"\nChecking {manual_name}{version_info}...")
        
        result = validate_message_against_manual(
            message=message,
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
        
        if not quiet:
            print(f"  {pdf_path.stem[:40]}: {status}")
        
        # Rate limiting (skip in quiet mode for parallel)
        if not quiet:
            time.sleep(0.5)
    
    # Summary
    if not quiet:
        print(f"\n=== Summary ===")
        print(f"  Found in {found_count}/{len(manuals)} manuals")
        print(f"  Matches: {match_count}")
        print(f"  Mismatches: {mismatch_count}")
    
    return results


def find_missing_bitfields(message: dict) -> list[dict]:
    """Find X-type fields without bitfield definitions."""
    missing = []
    for field in message.get("payload", {}).get("fields", []):
        data_type = field.get("data_type", "")
        if isinstance(data_type, str) and data_type.startswith("X"):
            if "bitfield" not in field:
                missing.append({
                    "name": field.get("name"),
                    "data_type": data_type,
                    "byte_offset": field.get("byte_offset"),
                })
    return missing


def extract_bitfield_from_pdf(
    message_name: str,
    field_name: str,
    data_type: str,
    pdf_path: Path,
    client: Any,
    verbose: bool = False,
) -> dict | None:
    """Extract a bitfield definition from a PDF manual."""
    from prompts.ubx_knowledge import build_bitfield_extraction_prompt

    pages = discover_message_pages(pdf_path, message_name)
    if not pages:
        if verbose:
            print(f"    Message not found in {pdf_path.stem}")
        return None

    start_page, end_page = pages
    temp_pdf = extract_pdf_pages(pdf_path, start_page, end_page)

    try:
        uploaded_file = client.files.upload(file=temp_pdf)
        prompt = build_bitfield_extraction_prompt(message_name, field_name, data_type)

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[uploaded_file, prompt],
        )

        # Clean up uploaded file
        try:
            client.files.delete(name=uploaded_file.name)
        except Exception:
            pass

        response_text = response.text.strip()

        # Extract JSON
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
                print(f"    Not found: {result.get('notes', '')[:50]}")
            return None

        return result

    except Exception as e:
        if verbose:
            print(f"    Error: {e}")
        return None
    finally:
        temp_pdf.unlink(missing_ok=True)


def extract_missing_bitfields(
    message_name: str,
    manuals: list[Path] | None = None,
    apply: bool = False,
    verbose: bool = False,
) -> dict:
    """Extract missing bitfield definitions from PDFs.

    Args:
        message_name: Name of message to process
        manuals: List of PDF paths (None = all manuals)
        apply: If True, apply extracted bitfields to schema
        verbose: Show detailed progress

    Returns:
        Dict with extraction results and statistics
    """
    from google import genai

    # Load canonical message
    canonical_messages = load_canonical_messages()
    if message_name not in canonical_messages:
        print(f"Error: Message '{message_name}' not found in canonical dataset")
        return {"error": "message_not_found"}

    message = canonical_messages[message_name]

    # Find missing bitfields
    missing = find_missing_bitfields(message)
    if not missing:
        print(f"{message_name}: No missing bitfields")
        return {"message": message_name, "missing": 0, "extracted": 0}

    print(f"{message_name}: {len(missing)} X-type fields without bitfields")
    for m in missing:
        print(f"  - {m['name']} ({m['data_type']})")

    # Get manuals - prefer F9 HPG for best documentation
    if manuals is None:
        manuals = find_pdf_manuals()

    # Sort manuals to try F9 HPG first (best documentation)
    def manual_priority(p: Path) -> int:
        name = p.stem.lower()
        if "f9-hpg" in name and "1.51" in name:
            return 0
        if "f9-hpg" in name:
            return 1
        if "f9" in name:
            return 2
        if "m10" in name:
            return 3
        return 4

    manuals = sorted(manuals, key=manual_priority)

    # Initialize client
    client = genai.Client()

    # Extract each missing bitfield
    extracted = {}
    for field_info in missing:
        field_name = field_info["name"]
        data_type = field_info["data_type"]

        print(f"\nExtracting {field_name} ({data_type})...")

        # Try manuals until we get a result
        for pdf_path in manuals[:5]:  # Try up to 5 manuals
            if verbose:
                print(f"  Trying {pdf_path.stem[:40]}...")

            result = extract_bitfield_from_pdf(
                message_name=message_name,
                field_name=field_name,
                data_type=data_type,
                pdf_path=pdf_path,
                client=client,
                verbose=verbose,
            )

            if result and "bitfield" in result:
                confidence = result.get("extraction_confidence", "unknown")
                print(f"  ✓ Extracted from {pdf_path.stem[:30]} (confidence: {confidence})")
                extracted[field_name] = result
                break
        else:
            print(f"  ✗ Not found in any manual")

    # Apply if requested
    if apply and extracted:
        apply_extracted_bitfields(message_name, extracted)

    return {
        "message": message_name,
        "missing": len(missing),
        "extracted": len(extracted),
        "fields": extracted,
    }


def apply_extracted_bitfields(message_name: str, extracted: dict):
    """Apply extracted bitfields to the canonical schema."""
    msgs_file = PROJECT_ROOT / "data" / "messages" / "ubx_messages.json"

    with open(msgs_file) as f:
        data = json.load(f)

    # Find and update the message
    for msg in data.get("messages", []):
        if msg["name"] == message_name:
            for field in msg.get("payload", {}).get("fields", []):
                field_name = field.get("name")
                if field_name in extracted:
                    bitfield_data = extracted[field_name].get("bitfield", [])
                    if bitfield_data:
                        # Convert to our schema format (remove description for compactness)
                        field["bitfield"] = [
                            {
                                "name": b["name"],
                                "bit_offset": b["bit_offset"],
                                "width": b["width"],
                            }
                            for b in bitfield_data
                        ]
                        print(f"  Applied bitfield to {field_name}")
            break

    # Save updated data
    with open(msgs_file, "w") as f:
        json.dump(data, f, indent=2)

    print(f"  Saved updates to {msgs_file.name}")


def save_results(message_name: str, results: list[ValidationResult]):
    """Save validation results to reports directory."""
    reports_dir = PROJECT_ROOT / "validation" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    # Save individual message results
    safe_name = message_name.replace("-", "_")
    results_file = reports_dir / f"{safe_name}_validation.json"
    
    with open(results_file, "w") as f:
        json.dump({
            "message": message_name,
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
    
    # Update overall status file with flock for parallel safety
    import fcntl
    status_file = reports_dir / "message_status.json"
    lock_file = reports_dir / "message_status.lock"
    
    with open(lock_file, "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            if status_file.exists():
                with open(status_file) as f:
                    status = json.load(f)
            else:
                status = {"messages": {}}
            
            # Determine overall status
            matches = [r for r in results if r.matches is True]
            mismatches = [r for r in results if r.matches is False]
            
            if not mismatches and matches:
                overall_status = "valid"
            elif mismatches:
                overall_status = "needs_review"
            else:
                overall_status = "unvalidated"
            
            status["messages"][message_name] = {
                "status": overall_status,
                "last_validated": datetime.now(timezone.utc).isoformat(),
                "manuals_checked": len(results),
                "matches": len(matches),
                "mismatches": len(mismatches),
            }
            
            with open(status_file, "w") as f:
                json.dump(status, f, indent=2)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(
        description="Validate a UBX message against PDF manuals"
    )
    parser.add_argument(
        "message",
        help="Message name (e.g., UBX-NAV-PVT)"
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
        help="Extract missing bitfield definitions from PDFs"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply extracted data to schema (use with --extract-missing)"
    )

    args = parser.parse_args()

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

    # Extract missing bitfields mode
    if args.extract_missing:
        result = extract_missing_bitfields(
            message_name=args.message,
            manuals=manuals,
            apply=args.apply,
            verbose=args.verbose,
        )
        if "error" in result:
            return 1
        print(f"\n=== Summary ===")
        print(f"  Missing bitfields: {result.get('missing', 0)}")
        print(f"  Extracted: {result.get('extracted', 0)}")
        if args.apply:
            print(f"  Applied to schema: Yes")
        else:
            print(f"  Applied to schema: No (use --apply to save)")
        return 0

    # Run validation
    results = validate_message(
        message_name=args.message,
        manuals=manuals,
        verbose=args.verbose,
    )

    if not results:
        return 1

    # Save results
    if not args.no_save:
        save_results(args.message, results)

    # Print discrepancies
    discrepancies = [r for r in results if r.matches is False]
    if discrepancies:
        print(f"\n=== Discrepancies Found ===")
        for r in discrepancies:
            print(f"\n{r.manual}:")
            for d in r.discrepancies:
                print(f"  - {d.get('field', 'unknown')}: {d.get('issue', 'no details')}")
            if r.notes:
                print(f"  Notes: {r.notes}")

    return 0 if not discrepancies else 2


if __name__ == "__main__":
    sys.exit(main())
