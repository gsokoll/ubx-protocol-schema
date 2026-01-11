#!/usr/bin/env python3
"""Generate a coverage report for the UBX protocol schema.

This script analyzes the schema and produces a report showing:
- Message coverage vs known messages
- Bitfield completion status
- Enumeration coverage
- Config key coverage

Run with: uv run python scripts/generate_coverage_report.py
"""

import json
from pathlib import Path
from datetime import datetime

# Paths
DATA_DIR = Path(__file__).parent.parent / "data"
MESSAGES_FILE = DATA_DIR / "messages" / "ubx_messages.json"
ENUMS_FILE = DATA_DIR / "messages" / "enumerations.json"
CONFIG_KEYS_FILE = DATA_DIR / "config_keys" / "unified_config_keys.json"
REPORT_FILE = Path(__file__).parent.parent / "COVERAGE.md"


def load_json(path: Path) -> dict:
    """Load JSON file."""
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def analyze_messages(data: dict) -> dict:
    """Analyze message coverage."""
    messages = data.get("messages", [])

    total_fields = 0
    x_type_fields = 0
    x_type_with_bitfield = 0
    x_type_missing_bitfield = []
    total_bitfield_bits = 0

    by_class = {}

    for msg in messages:
        name = msg["name"]
        # Extract class (e.g., NAV from UBX-NAV-PVT)
        parts = name.split("-")
        msg_class = parts[1] if len(parts) > 1 else "OTHER"
        by_class[msg_class] = by_class.get(msg_class, 0) + 1

        for field in msg.get("payload", {}).get("fields", []):
            total_fields += 1
            dt = field.get("data_type", "")

            if isinstance(dt, str) and dt.startswith("X"):
                x_type_fields += 1
                if "bitfield" in field:
                    x_type_with_bitfield += 1
                    total_bitfield_bits += len(field["bitfield"])
                else:
                    x_type_missing_bitfield.append({
                        "message": name,
                        "field": field["name"],
                        "type": dt
                    })

    return {
        "total_messages": len(messages),
        "by_class": by_class,
        "total_fields": total_fields,
        "x_type_fields": x_type_fields,
        "x_type_with_bitfield": x_type_with_bitfield,
        "x_type_missing_bitfield": x_type_missing_bitfield,
        "total_bitfield_bits": total_bitfield_bits,
    }


def analyze_enumerations(data: dict) -> dict:
    """Analyze enumeration coverage."""
    total_values = sum(len(e.get("values", [])) for e in data.values())
    messages_covered = set()
    for e in data.values():
        messages_covered.update(e.get("messages", []))

    return {
        "total_enumerations": len(data),
        "total_values": total_values,
        "messages_with_enums": len(messages_covered),
    }


def analyze_config_keys(data: dict) -> dict:
    """Analyze config key coverage."""
    groups = data.get("groups", {})
    keys = data.get("keys", [])

    by_type = {}
    for key in keys:
        dt = key.get("data_type", "unknown")
        by_type[dt] = by_type.get(dt, 0) + 1

    return {
        "total_groups": len(groups),
        "total_keys": len(keys),
        "by_type": by_type,
    }


def categorize_missing_bitfields(missing: list) -> dict:
    """Categorize missing bitfields by reason."""
    categories = {
        "gpio_masks": [],
        "adr_esf": [],
        "legacy": [],
        "security": [],
        "reserved": [],
        "other": [],
    }

    gpio_fields = {"pinBank", "pinDir", "pinVal", "pinSel", "usedMask"}
    adr_prefixes = ["ESF-", "HNR-", "PVAT"]
    legacy_msgs = ["AID-", "CFG-PM2", "CFG-TMODE2", "CFG-TXSLOT"]
    security_msgs = ["SEC-"]

    for item in missing:
        msg = item["message"]
        field = item["field"]

        if field in gpio_fields:
            categories["gpio_masks"].append(item)
        elif any(p in msg for p in adr_prefixes):
            categories["adr_esf"].append(item)
        elif any(p in msg for p in legacy_msgs):
            categories["legacy"].append(item)
        elif any(p in msg for p in security_msgs):
            categories["security"].append(item)
        elif "reserved" in field.lower():
            categories["reserved"].append(item)
        else:
            categories["other"].append(item)

    return categories


def generate_report() -> str:
    """Generate the coverage report."""
    # Load data
    messages_data = load_json(MESSAGES_FILE)
    enums_data = load_json(ENUMS_FILE)
    config_data = load_json(CONFIG_KEYS_FILE)

    # Analyze
    msg_stats = analyze_messages(messages_data)
    enum_stats = analyze_enumerations(enums_data)
    config_stats = analyze_config_keys(config_data)

    # Categorize missing bitfields
    missing_categories = categorize_missing_bitfields(msg_stats["x_type_missing_bitfield"])

    # Calculate completion percentages
    bitfield_pct = (msg_stats["x_type_with_bitfield"] / msg_stats["x_type_fields"] * 100) if msg_stats["x_type_fields"] > 0 else 100

    # Generate report
    lines = [
        "# UBX Protocol Schema Coverage Report",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Summary",
        "",
        "| Component | Count | Status |",
        "|-----------|-------|--------|",
        f"| Messages | {msg_stats['total_messages']} | Complete |",
        f"| Fields | {msg_stats['total_fields']} | Complete |",
        f"| Bitfield definitions | {msg_stats['x_type_with_bitfield']}/{msg_stats['x_type_fields']} ({bitfield_pct:.0f}%) | {len(msg_stats['x_type_missing_bitfield'])} missing |",
        f"| Bitfield bits defined | {msg_stats['total_bitfield_bits']} | - |",
        f"| Enumerations | {enum_stats['total_enumerations']} | {enum_stats['total_values']} values |",
        f"| Config key groups | {config_stats['total_groups']} | Complete |",
        f"| Config keys | {config_stats['total_keys']} | Complete |",
        "",
        "## Messages by Class",
        "",
        "| Class | Count |",
        "|-------|-------|",
    ]

    for cls, count in sorted(msg_stats["by_class"].items(), key=lambda x: -x[1]):
        lines.append(f"| {cls} | {count} |")

    lines.extend([
        "",
        "## Missing Bitfield Definitions",
        "",
        f"Total: {len(msg_stats['x_type_missing_bitfield'])} X-type fields without bitfield definitions",
        "",
    ])

    # Show categorized missing bitfields
    category_names = {
        "gpio_masks": "GPIO Pin Masks (raw bitmasks, no protocol-defined structure)",
        "adr_esf": "ADR/ESF Sensor Fusion (requires ADR-specific manual)",
        "legacy": "Legacy Messages (deprecated, not in current manuals)",
        "security": "Security Messages (SEC-OSNMA, etc.)",
        "reserved": "Reserved Fields",
        "other": "Other",
    }

    for cat_key, cat_name in category_names.items():
        items = missing_categories[cat_key]
        if items:
            lines.append(f"### {cat_name} ({len(items)})")
            lines.append("")
            for item in items:
                lines.append(f"- `{item['message']}`.`{item['field']}` ({item['type']})")
            lines.append("")

    lines.extend([
        "## Config Keys by Type",
        "",
        "| Type | Count |",
        "|------|-------|",
    ])

    for dtype, count in sorted(config_stats["by_type"].items(), key=lambda x: -x[1]):
        lines.append(f"| {dtype} | {count} |")

    lines.extend([
        "",
        "## Validation Status",
        "",
        "To validate the schema, run:",
        "",
        "```bash",
        "# Run round-trip tests",
        "cd testing && uv run pytest tests/test_round_trip.py -v",
        "",
        "# Cross-validate against pyubx2",
        "uv run python validation/scripts/cross_validate.py --summary",
        "",
        "# Regenerate this report",
        "uv run python scripts/generate_coverage_report.py",
        "```",
        "",
        "## Data Sources",
        "",
        "- **Messages**: Extracted from u-blox PDF interface descriptions",
        "- **Bitfields**: Extracted from PDF manuals via LLM",
        "- **Enumerations**: Extracted from PDF manuals",
        "- **Config Keys**: Extracted from PDF manuals",
        "",
        "Cross-validated against:",
        "- [pyubx2](https://github.com/semuconsulting/pyubx2) - Python UBX library",
        "- [ublox-rs](https://github.com/ublox-rs/ublox) - Rust UBX library",
    ])

    return "\n".join(lines)


def main():
    """Generate and save coverage report."""
    report = generate_report()

    with open(REPORT_FILE, "w") as f:
        f.write(report)

    print(f"Coverage report written to {REPORT_FILE}")
    print()
    print(report)


if __name__ == "__main__":
    main()
