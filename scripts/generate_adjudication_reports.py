#!/usr/bin/env python3
"""Generate human-readable adjudication reports for no-consensus messages.

This script creates detailed difference reports for messages that didn't reach
consensus during majority voting validation. These reports can be used for
manual adjudication or to understand where extractions differ.

Usage:
    uv run python scripts/generate_adjudication_reports.py

Output:
    analysis_reports/adjudication/
        MGA-INI-TIME-UTC-v0.md
        SEC-SIG-v1.md
        ...
"""

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.validation.version_detect import get_protocol_version


def load_extractions(extractions_dir: Path) -> dict:
    """Load all extraction files."""
    extractions = {}
    for f in sorted(extractions_dir.glob("*_anthropic.json")):
        data = json.loads(f.read_text())
        extractions[f.stem] = data
    return extractions


def get_message_variants(
    extractions: dict, message_name: str, protocol_version: int
) -> dict[str, dict]:
    """Get all variants of a message across extractions.
    
    Returns dict mapping source name to message data.
    """
    variants = {}
    
    for source_name, data in extractions.items():
        for msg in data.get("messages", []):
            if msg.get("name") == message_name:
                ver = get_protocol_version(msg)
                if ver == protocol_version:
                    # Simplify source name
                    short_name = source_name.replace("_anthropic", "")
                    if len(short_name) > 30:
                        short_name = short_name[:30] + "..."
                    variants[short_name] = msg
    
    return variants


def normalize_field(field: dict) -> dict:
    """Normalize a field for comparison."""
    dtype = field.get("data_type", "?")
    if isinstance(dtype, dict):
        if "array_of" in dtype:
            dtype = f"{dtype['array_of']}[{dtype.get('count', '?')}]"
        else:
            dtype = str(dtype)
    
    return {
        "name": field.get("name", "?"),
        "offset": field.get("byte_offset", "?"),
        "type": dtype,
        "description": (field.get("description") or "")[:60],
    }


def group_by_structure(variants: dict[str, dict]) -> dict[str, list[str]]:
    """Group sources by their field structure.
    
    Returns dict mapping structure signature to list of sources.
    """
    groups = defaultdict(list)
    
    for source, msg in variants.items():
        fields = msg.get("fields", [])
        if not fields and msg.get("payload"):
            fields = msg["payload"].get("fields", [])
        
        # Create structure signature
        sig_parts = []
        for f in sorted(fields, key=lambda x: x.get("byte_offset", 999)):
            nf = normalize_field(f)
            sig_parts.append(f"{nf['offset']}:{nf['name']}({nf['type']})")
        
        sig = "|".join(sig_parts)
        groups[sig].append(source)
    
    return dict(groups)


def find_field_differences(variants: dict[str, dict]) -> list[dict]:
    """Find specific field differences across variants.
    
    Returns list of difference records with offset, field info per source.
    """
    # Collect all fields by offset
    fields_by_offset = defaultdict(dict)
    
    for source, msg in variants.items():
        fields = msg.get("fields", [])
        if not fields and msg.get("payload"):
            fields = msg["payload"].get("fields", [])
        
        for f in fields:
            offset = f.get("byte_offset", -1)
            if offset >= 0:
                fields_by_offset[offset][source] = normalize_field(f)
    
    # Find differences
    differences = []
    for offset in sorted(fields_by_offset.keys()):
        sources_at_offset = fields_by_offset[offset]
        
        # Check if all sources have same field
        unique_fields = {}
        for source, field in sources_at_offset.items():
            key = (field["name"], field["type"])
            if key not in unique_fields:
                unique_fields[key] = {"field": field, "sources": []}
            unique_fields[key]["sources"].append(source)
        
        if len(unique_fields) > 1:
            differences.append({
                "offset": offset,
                "variants": [
                    {
                        "name": k[0],
                        "type": k[1],
                        "sources": v["sources"],
                        "description": v["field"]["description"],
                    }
                    for k, v in unique_fields.items()
                ],
            })
    
    return differences


def generate_report(
    message_name: str,
    protocol_version: int,
    variants: dict[str, dict],
    output_dir: Path,
) -> Path:
    """Generate a markdown adjudication report for a message."""
    
    groups = group_by_structure(variants)
    differences = find_field_differences(variants)
    
    # Sort groups by size (largest first)
    sorted_groups = sorted(groups.items(), key=lambda x: -len(x[1]))
    
    # Generate report
    lines = [
        f"# Adjudication Report: {message_name} v{protocol_version}",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Total sources:** {len(variants)}",
        f"**Unique structures:** {len(groups)}",
        "",
        "---",
        "",
        "## Summary",
        "",
    ]
    
    # Majority structure
    majority_sources = sorted_groups[0][1]
    lines.extend([
        f"**Majority structure:** {len(majority_sources)}/{len(variants)} sources",
        f"- Sources: {', '.join(majority_sources[:5])}{'...' if len(majority_sources) > 5 else ''}",
        "",
    ])
    
    # Minority structures
    if len(sorted_groups) > 1:
        lines.append("**Minority structures:**")
        for sig, sources in sorted_groups[1:]:
            lines.append(f"- {len(sources)} sources: {', '.join(sources[:3])}{'...' if len(sources) > 3 else ''}")
        lines.append("")
    
    lines.extend([
        "---",
        "",
        "## Field Differences",
        "",
    ])
    
    if not differences:
        lines.append("*No field-level differences found (difference may be in field count or order)*")
    else:
        for diff in differences:
            lines.append(f"### Offset {diff['offset']}")
            lines.append("")
            lines.append("| Variant | Name | Type | Sources | Description |")
            lines.append("|---------|------|------|---------|-------------|")
            
            for var in diff["variants"]:
                src_list = ", ".join(var["sources"][:3])
                if len(var["sources"]) > 3:
                    src_list += f" (+{len(var['sources'])-3} more)"
                desc = var["description"][:40] + "..." if len(var["description"]) > 40 else var["description"]
                lines.append(f"| **{var['name']}** | {var['name']} | {var['type']} | {src_list} | {desc} |")
            
            lines.append("")
    
    lines.extend([
        "---",
        "",
        "## Full Structure Comparison",
        "",
    ])
    
    # Show each unique structure
    for i, (sig, sources) in enumerate(sorted_groups, 1):
        # Get a representative message
        rep_source = sources[0]
        rep_msg = variants[rep_source]
        
        fields = rep_msg.get("fields", [])
        if not fields and rep_msg.get("payload"):
            fields = rep_msg["payload"].get("fields", [])
        
        lines.extend([
            f"### Structure {i} ({len(sources)} sources)",
            "",
            f"**Sources:** {', '.join(sources)}",
            "",
            "| Offset | Name | Type | Description |",
            "|--------|------|------|-------------|",
        ])
        
        for f in sorted(fields, key=lambda x: x.get("byte_offset", 999)):
            nf = normalize_field(f)
            desc = nf["description"][:50] + "..." if len(nf["description"]) > 50 else nf["description"]
            lines.append(f"| {nf['offset']} | {nf['name']} | {nf['type']} | {desc} |")
        
        lines.extend(["", ""])
    
    # Adjudication section
    lines.extend([
        "---",
        "",
        "## Adjudication Decision",
        "",
        "*To be filled in after manual review:*",
        "",
        "- [ ] Majority structure is correct",
        "- [ ] Minority structure is correct", 
        "- [ ] Both are valid (different firmware versions)",
        "- [ ] Extraction error - needs re-extraction",
        "",
        "**Decision:**",
        "",
        "**Rationale:**",
        "",
    ])
    
    # Write report
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename
    name_part = message_name.replace("UBX-", "")
    filename = f"{name_part}-v{protocol_version}.md"
    output_path = output_dir / filename
    
    output_path.write_text("\n".join(lines))
    return output_path


def main():
    project_root = Path(__file__).parent.parent
    extractions_dir = project_root / "data" / "by-manual"
    output_dir = project_root / "analysis_reports" / "adjudication"
    
    # Load discrepancy report to find no-consensus messages
    discrepancy_file = project_root / "analysis_reports" / "discrepancy_report.json"
    if not discrepancy_file.exists():
        print("Error: Run validate_majority.py first to generate discrepancy report")
        return 1
    
    report = json.loads(discrepancy_file.read_text())
    
    # Find no-consensus messages
    no_consensus = []
    for issue in report.get("issues", []):
        if issue.get("has_consensus") == False:
            no_consensus.append({
                "name": issue["message_name"],
                "version": issue["protocol_version"],
            })
    
    if not no_consensus:
        print("No no-consensus messages found!")
        return 0
    
    print(f"Found {len(no_consensus)} no-consensus messages")
    print()
    
    # Load extractions
    print("Loading extractions...")
    extractions = load_extractions(extractions_dir)
    print(f"Loaded {len(extractions)} extraction files")
    print()
    
    # Generate reports
    print("Generating adjudication reports:")
    for msg_info in no_consensus:
        name = msg_info["name"]
        version = msg_info["version"]
        
        variants = get_message_variants(extractions, name, version)
        
        if not variants:
            print(f"  {name} v{version}: No variants found")
            continue
        
        output_path = generate_report(name, version, variants, output_dir)
        print(f"  {name} v{version}: {len(variants)} variants -> {output_path.name}")
    
    print()
    print(f"Reports written to: {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
