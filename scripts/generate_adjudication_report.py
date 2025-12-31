#!/usr/bin/env python3
"""Generate a human-readable adjudication report from conflict detection results.

Reads the adjudication_queue.json and produces a markdown report for human review.
"""

import argparse
import json
from pathlib import Path


def generate_report(queue_file: Path, output_file: Path):
    """Generate markdown adjudication report."""
    
    with open(queue_file) as f:
        queue = json.load(f)
    
    # Group by field type
    by_field: dict[str, list] = {}
    for item in queue['items']:
        field = item['field']
        if field not in by_field:
            by_field[field] = []
        by_field[field].append(item)
    
    lines = []
    lines.append("# Config Key Adjudication Report\n")
    lines.append(f"**Total items needing review:** {len(queue['items'])}\n")
    lines.append("")
    lines.append("## Summary by Field\n")
    lines.append("| Field | Count |")
    lines.append("|-------|-------|")
    for field, items in sorted(by_field.items(), key=lambda x: -len(x[1])):
        lines.append(f"| {field} | {len(items)} |")
    lines.append("")
    
    # Generate sections for each field type
    for field in ['name', 'data_type', 'scale', 'unit']:
        items = by_field.get(field, [])
        if not items:
            continue
        
        lines.append(f"## {field.upper()} Conflicts ({len(items)} items)\n")
        
        for i, item in enumerate(items, 1):
            lines.append(f"### {i}. `{item['key_name']}` ({item['key_id']})\n")
            lines.append(f"**Confidence:** {item['confidence']:.1%} | **Suggested:** `{item['suggested']}`\n")
            lines.append("")
            lines.append("| Value | Sources | Count |")
            lines.append("|-------|---------|-------|")
            
            for c in item['candidates']:
                val = repr(c['value']) if isinstance(c['value'], str) else str(c['value'])
                if len(val) > 50:
                    val = val[:47] + "..."
                sources = ', '.join(c['sources'][:3])
                if len(c['sources']) > 3:
                    sources += f" +{len(c['sources'])-3} more"
                lines.append(f"| `{val}` | {sources} | {c['count']} |")
            
            lines.append("")
            lines.append(f"**Decision:** [ ] Use suggested / [ ] Use other: ____\n")
            lines.append("---\n")
    
    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text('\n'.join(lines))
    
    print(f"Report generated: {output_file}")
    print(f"Total items: {len(queue['items'])}")
    print("Items by field:")
    for field, items in sorted(by_field.items(), key=lambda x: -len(x[1])):
        print(f"  {field}: {len(items)}")


def main():
    parser = argparse.ArgumentParser(description="Generate adjudication report")
    parser.add_argument(
        "--queue",
        type=Path,
        default=Path("data/config_keys/adjudication_queue.json"),
        help="Path to adjudication queue JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/config_keys/adjudication_report.md"),
        help="Output markdown file",
    )
    args = parser.parse_args()
    
    if not args.queue.exists():
        print(f"Error: {args.queue} not found. Run detect_config_key_conflicts.py first.")
        return 1
    
    generate_report(args.queue, args.output)
    return 0


if __name__ == "__main__":
    exit(main())
