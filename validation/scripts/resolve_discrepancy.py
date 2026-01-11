#!/usr/bin/env python3
"""
Interactive tool to resolve validation discrepancies.

When validation finds mismatches, this tool helps:
1. Re-extract the specific field/message with focused prompts
2. Compare canonical vs PDF side-by-side
3. Mark as valid variation or fix the canonical

Usage:
    uv run python validation/scripts/resolve_discrepancy.py UBX-NAV-PVT
    uv run python validation/scripts/resolve_discrepancy.py --show-pending
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "validation"))

from validation.scripts.validate_message import (
    load_canonical_messages,
    load_manual_metadata,
    find_pdf_manuals,
    discover_message_pages,
    extract_pdf_pages,
    ManualMetadata,
)


def load_validation_status() -> dict:
    """Load message validation status."""
    status_file = PROJECT_ROOT / "validation" / "reports" / "message_status.json"
    if status_file.exists():
        with open(status_file) as f:
            return json.load(f)
    return {"messages": {}}


def load_message_validation_report(message_name: str) -> dict | None:
    """Load detailed validation report for a message."""
    safe_name = message_name.replace("-", "_")
    report_file = PROJECT_ROOT / "validation" / "reports" / f"{safe_name}_validation.json"
    if report_file.exists():
        with open(report_file) as f:
            return json.load(f)
    return None


def show_pending_discrepancies():
    """Show all messages needing review."""
    status = load_validation_status()
    messages = status.get("messages", {})
    
    needs_review = [
        (name, data) for name, data in messages.items()
        if data.get("status") == "needs_review"
    ]
    
    if not needs_review:
        print("No messages pending review.")
        return
    
    print(f"Messages needing review ({len(needs_review)}):\n")
    
    for name, data in sorted(needs_review, key=lambda x: -x[1].get("mismatches", 0)):
        print(f"  {name}")
        print(f"    Mismatches: {data.get('mismatches', 0)}/{data.get('manuals_checked', 0)} manuals")
        print(f"    Last checked: {data.get('last_validated', 'unknown')[:10]}")
        print()


def show_discrepancy_details(message_name: str):
    """Show detailed discrepancy information for a message."""
    report = load_message_validation_report(message_name)
    if not report:
        print(f"No validation report found for {message_name}")
        print(f"Run: uv run python validation/scripts/validate_message.py {message_name}")
        return
    
    print(f"=== Discrepancy Report: {message_name} ===\n")
    
    results = report.get("results", [])
    mismatches = [r for r in results if r.get("matches") is False]
    
    if not mismatches:
        print("No discrepancies found in validation report.")
        return
    
    print(f"Found {len(mismatches)} manual(s) with discrepancies:\n")
    
    for r in mismatches:
        print(f"--- {r.get('manual', 'unknown')[:50]} ---")
        if r.get("device_family") or r.get("protocol_version"):
            print(f"    Family: {r.get('device_family', '?')}, Protocol: {r.get('protocol_version', '?')}")
        
        discrepancies = r.get("discrepancies", [])
        for d in discrepancies:
            print(f"\n  Field: {d.get('field', 'unknown')}")
            print(f"  Issue: {d.get('issue', 'no details')[:100]}")
            if d.get("canonical_value"):
                print(f"  Canonical: {d.get('canonical_value')[:80]}")
            if d.get("pdf_value"):
                print(f"  PDF: {d.get('pdf_value')[:80]}")
        
        if r.get("notes"):
            print(f"\n  Notes: {r.get('notes')[:200]}")
        print()


def re_extract_field(
    message_name: str,
    field_name: str,
    pdf_path: Path,
    client: Any,
    metadata: ManualMetadata | None = None,
) -> dict | None:
    """Re-extract a specific field with focused prompt."""
    
    pages = discover_message_pages(pdf_path, message_name)
    if not pages:
        print(f"  Message not found in TOC")
        return None
    
    start_page, end_page = pages
    temp_pdf = extract_pdf_pages(pdf_path, start_page, end_page)
    
    try:
        uploaded_file = client.files.upload(file=temp_pdf)
        
        prompt = f"""Extract the EXACT definition of field "{field_name}" from the {message_name} message.

Look for:
1. The field in the payload table
2. Its byte offset, data type, and size
3. Any bitfield definitions if it's an X-type
4. Scale factors and units
5. Enumeration values if applicable

Return a JSON object with the field definition:
```json
{{
  "name": "{field_name}",
  "byte_offset": <number>,
  "data_type": "<type>",
  "description": "<description>",
  "bitfield": {{ ... }},  // if applicable
  "enumeration": {{ ... }},  // if applicable
  "scale": {{ ... }},  // if applicable
  "unit": "<unit>"  // if applicable
}}
```

If the field is not found, return:
```json
{{
  "error": "Field not found",
  "notes": "<explanation>"
}}
```
"""
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
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
        
        return json.loads(response_text)
        
    except Exception as e:
        print(f"  Error: {e}")
        return None
    finally:
        temp_pdf.unlink(missing_ok=True)


def resolve_interactive(message_name: str, manual_filter: str | None = None):
    """Interactive resolution of discrepancies."""
    from google import genai
    
    report = load_message_validation_report(message_name)
    if not report:
        print(f"No validation report found for {message_name}")
        return
    
    canonical_messages = load_canonical_messages()
    canonical = canonical_messages.get(message_name)
    if not canonical:
        print(f"Message {message_name} not found in canonical dataset")
        return
    
    results = report.get("results", [])
    mismatches = [r for r in results if r.get("matches") is False]
    
    if manual_filter:
        mismatches = [r for r in mismatches if manual_filter.lower() in r.get("manual", "").lower()]
    
    if not mismatches:
        print("No discrepancies to resolve.")
        return
    
    print(f"\n=== Resolving discrepancies for {message_name} ===\n")
    
    # Show canonical structure summary
    payload = canonical.get("payload", {})
    fields = payload.get("fields", [])
    print(f"Canonical: {len(fields)} fields, length={payload.get('length', {})}")
    
    # Process each mismatch
    all_metadata = load_manual_metadata()
    manuals = find_pdf_manuals()
    client = genai.Client()
    
    for r in mismatches:
        manual_name = r.get("manual", "")
        print(f"\n--- {manual_name[:50]} ---")
        print(f"Protocol: {r.get('protocol_version')}, Family: {r.get('device_family')}")
        
        discrepancies = r.get("discrepancies", [])
        
        for d in discrepancies:
            field_name = d.get("field", "unknown")
            print(f"\nField: {field_name}")
            print(f"Issue: {d.get('issue', '')[:100]}")
            
            # Offer options
            print("\nOptions:")
            print("  [r] Re-extract this field from PDF")
            print("  [v] Mark as valid variation")
            print("  [f] Fix canonical (opens editor)")
            print("  [s] Skip")
            print("  [q] Quit")
            
            choice = input("\nChoice: ").strip().lower()
            
            if choice == "q":
                return
            elif choice == "s":
                continue
            elif choice == "v":
                # Record as valid variation
                record_valid_variation(message_name, field_name, r)
                print("  Recorded as valid variation.")
            elif choice == "r":
                # Re-extract field
                pdf_path = next((m for m in manuals if manual_name in m.stem), None)
                if pdf_path:
                    metadata = all_metadata.get(manual_name)
                    print(f"  Re-extracting {field_name}...")
                    result = re_extract_field(
                        message_name, field_name, pdf_path, client, metadata
                    )
                    if result:
                        print(f"  Extracted: {json.dumps(result, indent=2)}")
                else:
                    print(f"  PDF not found: {manual_name}")
            elif choice == "f":
                print("  Manual editing not implemented - edit data/messages/ubx_messages.json directly")


def adjudicate_with_llm(
    message_name: str,
    canonical: dict,
    discrepancy: dict,
    validation_result: dict,
    pdf_path: Path,
    client: Any,
    metadata: ManualMetadata | None = None,
) -> dict:
    """Use LLM to adjudicate a discrepancy.
    
    Returns:
        {
            "decision": "fix_canonical" | "valid_variation" | "needs_human",
            "confidence": float (0-1),
            "reasoning": str,
            "suggested_fix": dict | None
        }
    """
    pages = discover_message_pages(pdf_path, message_name)
    if not pages:
        return {
            "decision": "needs_human",
            "confidence": 0.0,
            "reasoning": "Message not found in PDF TOC",
            "suggested_fix": None,
        }
    
    start_page, end_page = pages
    temp_pdf = extract_pdf_pages(pdf_path, start_page, end_page)
    
    try:
        uploaded_file = client.files.upload(file=temp_pdf)
        
        field_name = discrepancy.get("field", "unknown")
        issue = discrepancy.get("issue", "")
        canonical_value = discrepancy.get("canonical_value", "")
        pdf_value = discrepancy.get("pdf_value", "")
        
        prompt = f"""You are adjudicating a discrepancy between a canonical UBX message definition and a PDF manual.

Message: {message_name}
Manual: {validation_result.get('manual', 'unknown')}
Protocol Version: {validation_result.get('protocol_version', 'unknown')}
Device Family: {validation_result.get('device_family', 'unknown')}

Discrepancy:
- Field: {field_name}
- Issue: {issue}
- Canonical value: {canonical_value}
- PDF value: {pdf_value}

Canonical definition excerpt:
{json.dumps(canonical.get('payload', {}), indent=2)[:2000]}

Analyze the PDF pages provided and determine:

1. Is the canonical definition WRONG and should be fixed?
2. Is this a VALID VARIATION (e.g., different protocol versions have different fields)?
3. Is this unclear and NEEDS HUMAN review?

Respond with JSON:
```json
{{
  "decision": "fix_canonical" | "valid_variation" | "needs_human",
  "confidence": 0.0-1.0,
  "reasoning": "<brief explanation>",
  "suggested_fix": null or {{
    "field": "<field_name>",
    "change": "<what to change>",
    "new_value": "<new value if applicable>"
  }}
}}
```
"""
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
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
        
        return json.loads(response_text)
        
    except Exception as e:
        return {
            "decision": "needs_human",
            "confidence": 0.0,
            "reasoning": f"Error during adjudication: {e}",
            "suggested_fix": None,
        }
    finally:
        temp_pdf.unlink(missing_ok=True)


def adjudicate_message_auto(message_name: str, save_results: bool = True) -> dict:
    """Auto-adjudicate all discrepancies for a message using LLM."""
    from google import genai
    
    report = load_message_validation_report(message_name)
    if not report:
        print(f"No validation report found for {message_name}")
        return {"error": "No report"}
    
    canonical_messages = load_canonical_messages()
    canonical = canonical_messages.get(message_name)
    if not canonical:
        print(f"Message {message_name} not found in canonical dataset")
        return {"error": "No canonical"}
    
    results = report.get("results", [])
    mismatches = [r for r in results if r.get("matches") is False]
    
    if not mismatches:
        print(f"{message_name}: No discrepancies")
        return {"status": "clean"}
    
    all_metadata = load_manual_metadata()
    manuals = find_pdf_manuals()
    client = genai.Client()
    
    adjudications = []
    
    for r in mismatches:
        manual_name = r.get("manual", "")
        pdf_path = next((m for m in manuals if manual_name in m.stem), None)
        
        if not pdf_path:
            continue
        
        metadata = all_metadata.get(manual_name)
        
        for d in r.get("discrepancies", []):
            print(f"  Adjudicating {d.get('field', '?')} in {manual_name[:30]}...")
            
            result = adjudicate_with_llm(
                message_name=message_name,
                canonical=canonical,
                discrepancy=d,
                validation_result=r,
                pdf_path=pdf_path,
                client=client,
                metadata=metadata,
            )
            
            adjudications.append({
                "manual": manual_name,
                "field": d.get("field"),
                "original_issue": d.get("issue"),
                **result,
            })
            
            decision = result.get("decision", "?")
            confidence = result.get("confidence", 0)
            print(f"    -> {decision} (confidence: {confidence:.0%})")
    
    # Summary
    fix_count = sum(1 for a in adjudications if a.get("decision") == "fix_canonical")
    variation_count = sum(1 for a in adjudications if a.get("decision") == "valid_variation")
    human_count = sum(1 for a in adjudications if a.get("decision") == "needs_human")
    
    summary = {
        "message": message_name,
        "total_discrepancies": len(adjudications),
        "fix_canonical": fix_count,
        "valid_variation": variation_count,
        "needs_human": human_count,
        "adjudications": adjudications,
    }
    
    if save_results:
        safe_name = message_name.replace("-", "_")
        adj_file = PROJECT_ROOT / "validation" / "reports" / f"{safe_name}_adjudication.json"
        with open(adj_file, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"  Saved to {adj_file.name}")
    
    return summary


def record_valid_variation(message_name: str, field_name: str, validation_result: dict):
    """Record a field as having a valid variation."""
    variations_file = PROJECT_ROOT / "validation" / "reports" / "valid_variations.json"
    
    if variations_file.exists():
        with open(variations_file) as f:
            variations = json.load(f)
    else:
        variations = {"variations": []}
    
    variations["variations"].append({
        "message": message_name,
        "field": field_name,
        "manual": validation_result.get("manual"),
        "protocol_version": validation_result.get("protocol_version"),
        "device_family": validation_result.get("device_family"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    })
    
    with open(variations_file, "w") as f:
        json.dump(variations, f, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Resolve validation discrepancies"
    )
    parser.add_argument(
        "message",
        nargs="?",
        help="Message name to resolve"
    )
    parser.add_argument(
        "--show-pending",
        action="store_true",
        help="Show all messages pending review"
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Show detailed discrepancies (non-interactive)"
    )
    parser.add_argument(
        "--manual",
        help="Filter to specific manual"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-adjudicate using LLM (non-interactive)"
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process all pending messages (with --auto)"
    )
    
    args = parser.parse_args()
    
    if args.show_pending:
        show_pending_discrepancies()
        return 0
    
    if not args.message:
        parser.print_help()
        return 1
    
    if args.details:
        show_discrepancy_details(args.message)
        return 0
    
    # Auto-adjudication mode
    if args.auto:
        if not os.environ.get("GOOGLE_API_KEY"):
            print("Error: GOOGLE_API_KEY not set")
            return 1
        
        if args.batch:
            # Process all pending
            status = load_validation_status()
            pending = [
                name for name, data in status.get("messages", {}).items()
                if data.get("status") == "needs_review"
            ]
            print(f"Auto-adjudicating {len(pending)} messages...\n")
            for msg in sorted(pending):
                print(f"\n=== {msg} ===")
                adjudicate_message_auto(msg)
        elif args.message:
            adjudicate_message_auto(args.message)
        else:
            print("Specify a message or use --batch")
            return 1
        return 0
    
    # Check API key for interactive mode
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set (required for re-extraction)")
        print("Use --details for non-interactive view")
        return 1
    
    resolve_interactive(args.message, args.manual)
    return 0


if __name__ == "__main__":
    sys.exit(main())
