#!/usr/bin/env python3
"""
Validate UBX enumeration definitions against PDF manuals.

Enumerations are validated by finding the message that uses them and checking
the enum values against the PDF description.

Usage:
    uv run python validation/scripts/validate_enumerations.py timeRef
    uv run python validation/scripts/validate_enumerations.py --list
    uv run python validation/scripts/validate_enumerations.py --all
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "validation"))

from validation.scripts.validate_message import (
    ManualMetadata,
    load_manual_metadata,
    find_pdf_manuals,
    discover_message_pages,
    extract_pdf_pages,
)


@dataclass
class EnumValidationResult:
    """Result of validating an enumeration against a manual."""
    manual: str
    enum_name: str
    message_context: str  # Message where enum appears
    matches: bool | None
    confidence: str
    discrepancies: list[dict]
    notes: str
    protocol_version: int | None = None
    device_family: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> dict:
        return {
            "manual": self.manual,
            "enum_name": self.enum_name,
            "message_context": self.message_context,
            "matches": self.matches,
            "confidence": self.confidence,
            "discrepancies": self.discrepancies,
            "notes": self.notes,
            "protocol_version": self.protocol_version,
            "device_family": self.device_family,
            "timestamp": self.timestamp,
        }


def load_enumerations() -> dict[str, dict]:
    """Load enumeration definitions."""
    enum_file = PROJECT_ROOT / "data" / "messages" / "enumerations.json"
    with open(enum_file) as f:
        return json.load(f)


# Map enumerations to the messages that use them
ENUM_MESSAGE_MAP = {
    "timeRef": ["UBX-CFG-RATE", "UBX-CFG-TP5"],
    "datumNum": ["UBX-CFG-DAT"],
    "resetMode": ["UBX-CFG-RST"],
    "fixType": ["UBX-NAV-PVT", "UBX-NAV-STATUS"],
    "gnssId": ["UBX-NAV-SAT", "UBX-NAV-SIG", "UBX-MON-GNSS"],
    "nmeaVersion": ["UBX-CFG-NMEA"],
    "tpIdx": ["UBX-CFG-TP5"],
    "pioEnabled": ["UBX-CFG-GEOFENCE"],
    "pinPolarity": ["UBX-CFG-GEOFENCE"],
    "state": ["UBX-MON-HW"],
}


def build_enum_validation_prompt(enum_name: str, enum_data: dict, message_name: str) -> str:
    """Build validation prompt for an enumeration."""
    values_str = json.dumps(enum_data.get("values", []), indent=2)
    
    return f"""You are validating enumeration values for a UBX protocol field.

## ENUMERATION TO VALIDATE

Field name: {enum_name}
Message context: {message_name}

Canonical enumeration values:
```json
{values_str}
```

## YOUR TASK

Find the field "{enum_name}" in the message description and compare its enumeration values
against the canonical definition above.

Look for:
1. A field named "{enum_name}" or similar in the payload table
2. The enumeration values listed in the description or a sub-table
3. Value numbers and their meanings

## RESPONSE FORMAT

Return a JSON object:
```json
{{
  "matches": true | false,
  "confidence": "high" | "medium" | "low",
  "discrepancies": [
    {{
      "value": 0,
      "issue": "description of mismatch",
      "canonical": "what canonical says",
      "pdf": "what PDF shows"
    }}
  ],
  "notes": "any observations about version differences, missing values, etc."
}}
```

If the enumeration field is not found in this message, return:
```json
{{
  "matches": null,
  "confidence": "high",
  "discrepancies": [],
  "notes": "Field not found in this message"
}}
```
"""


def validate_enum_against_manual(
    enum_name: str,
    enum_data: dict,
    message_name: str,
    pdf_path: Path,
    client: Any,
    metadata: ManualMetadata | None = None,
    model: str = "gemini-2.5-flash",
    verbose: bool = False,
) -> EnumValidationResult:
    """Validate an enumeration against a PDF manual."""
    
    manual_name = pdf_path.stem
    
    # Find message pages
    pages = discover_message_pages(pdf_path, message_name)
    if not pages:
        return EnumValidationResult(
            manual=manual_name,
            enum_name=enum_name,
            message_context=message_name,
            matches=None,
            confidence="high",
            discrepancies=[],
            notes=f"Message {message_name} not found in TOC",
            protocol_version=metadata.protocol_version if metadata else None,
            device_family=metadata.device_family if metadata else None,
        )
    
    start_page, end_page = pages
    if verbose:
        print(f"  Found {message_name} on pages {start_page}-{end_page}")
    
    temp_pdf = extract_pdf_pages(pdf_path, start_page, end_page)
    
    try:
        uploaded_file = client.files.upload(file=temp_pdf)
        prompt = build_enum_validation_prompt(enum_name, enum_data, message_name)
        
        response = client.models.generate_content(
            model=model,
            contents=[uploaded_file, prompt],
        )
        
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
        
        result_data = json.loads(response_text)
        
        return EnumValidationResult(
            manual=manual_name,
            enum_name=enum_name,
            message_context=message_name,
            matches=result_data.get("matches"),
            confidence=result_data.get("confidence", "medium"),
            discrepancies=result_data.get("discrepancies", []),
            notes=result_data.get("notes", ""),
            protocol_version=metadata.protocol_version if metadata else None,
            device_family=metadata.device_family if metadata else None,
        )
        
    except Exception as e:
        return EnumValidationResult(
            manual=manual_name,
            enum_name=enum_name,
            message_context=message_name,
            matches=None,
            confidence="low",
            discrepancies=[],
            notes=f"Validation error: {e}",
            protocol_version=metadata.protocol_version if metadata else None,
            device_family=metadata.device_family if metadata else None,
        )
    finally:
        temp_pdf.unlink(missing_ok=True)


def validate_enumeration(
    enum_name: str,
    manuals: list[Path] | None = None,
    verbose: bool = False,
) -> list[EnumValidationResult]:
    """Validate an enumeration against manuals."""
    
    from google import genai
    
    enums = load_enumerations()
    if enum_name not in enums:
        print(f"Error: Enumeration '{enum_name}' not found")
        return []
    
    enum_data = enums[enum_name]
    
    # Get messages that use this enum
    messages = ENUM_MESSAGE_MAP.get(enum_name, [])
    if not messages:
        print(f"Warning: No known messages use enumeration '{enum_name}'")
        # Try first message as fallback
        messages = ["UBX-CFG-RATE"]
    
    if manuals is None:
        manuals = find_pdf_manuals()
    
    all_metadata = load_manual_metadata()
    client = genai.Client()
    
    results = []
    
    print(f"Validating enumeration '{enum_name}' ({len(enum_data.get('values', []))} values)")
    print(f"Context messages: {messages}")
    
    for pdf_path in manuals[:5]:  # Limit to 5 manuals for enums
        manual_name = pdf_path.stem
        metadata = all_metadata.get(manual_name)
        
        for message_name in messages[:1]:  # Use first message
            if verbose:
                print(f"\nChecking {manual_name} / {message_name}...")
            
            result = validate_enum_against_manual(
                enum_name=enum_name,
                enum_data=enum_data,
                message_name=message_name,
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
            else:
                status = f"✗ {len(result.discrepancies)} discrepancies"
            
            print(f"  {manual_name[:35]}: {status}")
            time.sleep(0.5)
    
    return results


def save_results(enum_name: str, results: list[EnumValidationResult]):
    """Save validation results."""
    reports_dir = PROJECT_ROOT / "validation" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    results_file = reports_dir / f"enum_{enum_name}_validation.json"
    
    with open(results_file, "w") as f:
        json.dump({
            "enumeration": enum_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": [r.to_dict() for r in results],
        }, f, indent=2)
    
    print(f"Results saved to: {results_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Validate UBX enumerations against PDF manuals"
    )
    parser.add_argument(
        "enum_name",
        nargs="?",
        help="Enumeration name (e.g., timeRef)"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available enumerations"
    )
    parser.add_argument(
        "--manual",
        help="Specific manual to check"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    if args.list:
        enums = load_enumerations()
        print(f"Available enumerations ({len(enums)}):")
        for name, data in sorted(enums.items()):
            values = data.get("values", [])
            messages = ENUM_MESSAGE_MAP.get(name, ["unknown"])
            print(f"  {name}: {len(values)} values (used in {messages[0]})")
        return 0
    
    if not args.enum_name:
        parser.print_help()
        return 1
    
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set")
        return 1
    
    manuals = None
    if args.manual:
        all_manuals = find_pdf_manuals()
        manuals = [m for m in all_manuals if args.manual.lower() in m.stem.lower()]
    
    results = validate_enumeration(
        enum_name=args.enum_name,
        manuals=manuals,
        verbose=args.verbose,
    )
    
    if results:
        save_results(args.enum_name, results)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
