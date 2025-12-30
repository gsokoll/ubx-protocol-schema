#!/usr/bin/env python3
"""Re-extract outlier messages from their original manuals.

For each no-consensus message, identifies which manual extractions were
outliers and re-extracts those specific messages from their original PDFs,
updating the per-manual extraction files.
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


def load_discrepancy_report(project_root: Path) -> dict:
    """Load the discrepancy report."""
    report_path = project_root / "analysis_reports" / "discrepancy_report.json"
    if not report_path.exists():
        return {}
    return json.loads(report_path.read_text())


def build_source_to_file_map(extractions_dir: Path) -> dict[str, Path]:
    """Map source short names to extraction file paths."""
    mapping = {}
    for f in extractions_dir.glob("*_anthropic.json"):
        source = parse_source_from_filename(f.name)
        mapping[source.short_name] = f
    return mapping


def build_source_to_pdf_map(project_root: Path) -> dict[str, Path]:
    """Map source short names to PDF file paths."""
    manuals_json = project_root / "interface_manuals" / "manuals.json"
    data = json.loads(manuals_json.read_text())
    
    mapping = {}
    for module_name, module_data in data.items():
        for manual in module_data.get("manuals", []):
            local_path = project_root / manual.get("local_path", "")
            if local_path.exists():
                # Parse source from PDF filename
                source = parse_source_from_filename(local_path.name)
                if source.short_name != "UNKNOWN-UNKNOWN-0.0":
                    mapping[source.short_name] = local_path
    return mapping


def build_reextraction_prompt(
    message_name: str,
    discrepancy: str,
    discrepancy_details: list[dict] | None = None,
    consensus_fields: list[dict] | None = None,
) -> str:
    """Build a prompt with specific error context for re-extraction.
    
    Args:
        message_name: Name of message to re-extract
        discrepancy: Summary string of what's wrong
        discrepancy_details: Detailed field-by-field differences from report
        consensus_fields: Expected field structure from consensus
    """
    
    lines = [
        f"Re-extract message {message_name} from the PDF pages.",
        "",
        "IMPORTANT: Your previous extraction disagreed with consensus from other manuals.",
        "",
    ]
    
    # Add detailed field-by-field comparison if available
    if discrepancy_details:
        lines.append("SPECIFIC ERRORS IN PREVIOUS EXTRACTION:")
        lines.append("")
        
        for detail in discrepancy_details[:12]:  # Limit to 12 differences
            offset = detail.get('offset', '?')
            diff_type = detail.get('type', '')
            
            if diff_type == 'field_differs':
                first = detail.get('first', {})
                second = detail.get('second', {})
                consensus_name = first.get('original_name', '?')
                consensus_type = first.get('original_data_type', '?')
                outlier_name = second.get('original_name', '?')
                outlier_type = second.get('original_data_type', '?')
                
                lines.append(f"  Offset {offset}:")
                lines.append(f"    EXPECTED (consensus): {consensus_name} ({consensus_type})")
                lines.append(f"    YOUR EXTRACTION:      {outlier_name} ({outlier_type}) ← WRONG")
                lines.append("")
                
            elif diff_type == 'missing_in_second':
                first = detail.get('first', {})
                consensus_name = first.get('original_name', '?')
                consensus_type = first.get('original_data_type', '?')
                lines.append(f"  Offset {offset}:")
                lines.append(f"    EXPECTED (consensus): {consensus_name} ({consensus_type})")
                lines.append(f"    YOUR EXTRACTION:      MISSING ← You missed this field")
                lines.append("")
                
            elif diff_type == 'missing_in_first':
                second = detail.get('second', {})
                outlier_name = second.get('original_name', '?')
                outlier_type = second.get('original_data_type', '?')
                lines.append(f"  Offset {offset}:")
                lines.append(f"    EXPECTED (consensus): (no field here)")
                lines.append(f"    YOUR EXTRACTION:      {outlier_name} ({outlier_type}) ← Extra field")
                lines.append("")
        
        if len(discrepancy_details) > 12:
            lines.append(f"  ... and {len(discrepancy_details) - 12} more differences")
            lines.append("")
    else:
        # Fallback to summary if no details
        lines.append(f"Discrepancy summary: {discrepancy}")
        lines.append("")
    
    # Add consensus field structure for reference
    if consensus_fields:
        lines.append("CORRECT FIELD STRUCTURE (from consensus of other manuals):")
        for f in consensus_fields[:20]:
            offset = f.get('byte_offset', '?')
            name = f.get('name', '?')
            dtype = f.get('data_type', '?')
            lines.append(f"  offset {offset}: {name} ({dtype})")
        if len(consensus_fields) > 20:
            lines.append(f"  ... and {len(consensus_fields) - 20} more fields")
        lines.append("")
    
    lines.extend([
        "INSTRUCTIONS:",
        "1. Look carefully at the PDF - extract exactly what's shown there",
        "2. Pay special attention to the fields marked WRONG above",
        "3. Ensure byte offsets are sequential with no gaps",
        "4. If the PDF truly shows different fields than consensus, extract what the PDF shows",
        "   (some protocol versions may legitimately differ)",
    ])
    
    return "\n".join(lines)


def update_message_in_file(
    extraction_file: Path,
    message_name: str,
    new_message_data: dict,
) -> bool:
    """Update a specific message in an extraction file."""
    data = json.loads(extraction_file.read_text())
    
    messages = data.get("messages", [])
    updated = False
    
    for i, msg in enumerate(messages):
        if msg.get("name") == message_name:
            messages[i] = new_message_data
            updated = True
            break
    
    if updated:
        data["messages"] = messages
        extraction_file.write_text(json.dumps(data, indent=2))
    
    return updated


def reextract_outlier(
    project_root: Path,
    message_name: str,
    source_name: str,
    discrepancy: str,
    discrepancy_details: list[dict] | None,
    pdf_path: Path,
    consensus_fields: list[dict] | None = None,
    model: str = "claude-sonnet-4-20250514",
    max_pages: int = 3,
) -> dict | None:
    """Re-extract a single outlier message from its original PDF."""
    
    # Find message location in PDF
    locations = find_message_locations(pdf_path, [message_name])
    if message_name not in locations:
        print(f"    ERROR: Message not found in PDF TOC")
        return None
    
    loc = locations[message_name]
    page_end = min(loc.page_end, loc.page_start + max_pages)
    
    print(f"    Pages: {loc.page_start}-{page_end}")
    
    # Extract page images
    images = extract_pages_as_images_cropped(
        pdf_path,
        loc.page_start,
        page_end,
        crop_top_ratio=0.095,
        crop_bottom_ratio=0.085,
    )
    
    # Build prompt with detailed discrepancy context
    prompt_context = build_reextraction_prompt(
        message_name, discrepancy, discrepancy_details, consensus_fields
    )
    
    print(f"    Calling Claude ({len(images)} pages)...")
    try:
        raw, usage = call_claude_for_extraction(
            images=images,
            message_name=message_name,
            expected_class_id=loc.class_id or None,
            expected_message_id=loc.message_id or None,
            model=model,
            max_tokens=8192,
            additional_context=prompt_context,
        )
        
        result = normalize_extraction(raw, message_name, "reextract")
        
        if result.success:
            return result.message
        else:
            print(f"    ERROR: {result.errors}")
            return None
            
    except Exception as e:
        print(f"    ERROR: {e}")
        return None


def get_consensus_fields(project_root: Path, message_name: str, protocol_version: int) -> list[dict] | None:
    """Get the consensus field structure for a message."""
    validated_file = project_root / "data" / "validated" / "messages" / f"{message_name.replace('UBX-', '')}-v{protocol_version}.json"
    if validated_file.exists():
        data = json.loads(validated_file.read_text())
        return data.get("payload", {}).get("fields", [])
    return None


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        return 2
    
    project_root = Path(__file__).parent.parent
    extractions_dir = project_root / "data" / "by-manual"
    
    # Load report and build mappings
    report = load_discrepancy_report(project_root)
    if not report:
        print("Error: No discrepancy report found. Run validate_majority.py first.")
        return 1
    
    source_to_file = build_source_to_file_map(extractions_dir)
    source_to_pdf = build_source_to_pdf_map(project_root)
    
    print(f"Loaded {len(source_to_file)} extraction files")
    print(f"Loaded {len(source_to_pdf)} PDF mappings")
    
    # Collect all outliers to re-extract
    reextraction_tasks = []
    
    for issue in report.get("issues", []):
        if not issue.get("has_consensus", True):
            # No consensus - all sources are potential outliers
            # Re-extract from outliers only (not agreeing sources)
            message_name = issue["message_name"]
            protocol_version = issue.get("protocol_version", 0)
            
            for outlier in issue.get("outliers", []):
                source = outlier["source"]
                discrepancy = outlier.get("discrepancy", "unknown")
                details = outlier.get("details", [])
                
                if source in source_to_file and source in source_to_pdf:
                    reextraction_tasks.append({
                        "message_name": message_name,
                        "protocol_version": protocol_version,
                        "source": source,
                        "discrepancy": discrepancy,
                        "discrepancy_details": details,
                        "extraction_file": source_to_file[source],
                        "pdf_path": source_to_pdf[source],
                    })
    
    print(f"\nFound {len(reextraction_tasks)} outlier extractions to re-extract")
    
    if not reextraction_tasks:
        print("Nothing to re-extract.")
        return 0
    
    # Show summary by message
    by_message = {}
    for task in reextraction_tasks:
        msg = task["message_name"]
        if msg not in by_message:
            by_message[msg] = []
        by_message[msg].append(task["source"])
    
    print("\nOutliers by message:")
    for msg, sources in sorted(by_message.items()):
        print(f"  {msg}: {len(sources)} outliers")
    
    # Estimate cost
    estimated_cost = len(reextraction_tasks) * 0.30
    print(f"\nEstimated cost: ~${estimated_cost:.2f}")
    response = input("Proceed with re-extraction? [y/N] ")
    if response.lower() != 'y':
        print("Aborted.")
        return 0
    
    success_count = 0
    failed = []
    total = len(reextraction_tasks)
    
    import time
    start_time = time.time()
    
    for i, task in enumerate(reextraction_tasks, 1):
        msg_name = task["message_name"]
        source = task["source"]
        
        # Progress with percentage and ETA
        pct = (i - 1) / total * 100
        elapsed = time.time() - start_time
        if i > 1:
            avg_time = elapsed / (i - 1)
            remaining = avg_time * (total - i + 1)
            eta = f"ETA: {remaining/60:.1f}min"
        else:
            eta = ""
        
        print(f"\n[{i}/{total}] ({pct:.0f}%) {msg_name} from {source} {eta}")
        print(f"    Discrepancy: {task['discrepancy'][:60]}...")
        
        # Get consensus fields for reference
        consensus_fields = get_consensus_fields(
            project_root, msg_name, task["protocol_version"]
        )
        
        try:
            result = reextract_outlier(
                project_root,
                msg_name,
                source,
                task["discrepancy"],
                task["discrepancy_details"],
                task["pdf_path"],
                consensus_fields,
            )
            
            if result:
                # Update the extraction file
                updated = update_message_in_file(
                    task["extraction_file"],
                    msg_name,
                    result,
                )
                if updated:
                    print(f"    ✅ Updated in {task['extraction_file'].name}")
                    success_count += 1
                else:
                    print(f"    ⚠️  Message not found in extraction file")
                    failed.append(f"{msg_name}@{source}")
            else:
                failed.append(f"{msg_name}@{source}")
                
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
            break
        except Exception as e:
            print(f"    ❌ Exception: {e}")
            failed.append(f"{msg_name}@{source}")
    
    print(f"\n{'='*60}")
    print(f"Re-extraction complete: {success_count}/{len(reextraction_tasks)} successful")
    
    if failed:
        print(f"\nFailed ({len(failed)}):")
        for f in failed[:10]:
            print(f"  - {f}")
        if len(failed) > 10:
            print(f"  ... and {len(failed) - 10} more")
    
    print("\nNext step: Re-run validate_majority.py to check improved consensus")
    
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
