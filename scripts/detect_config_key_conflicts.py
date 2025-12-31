#!/usr/bin/env python3
"""Detect conflicts in config key extractions across multiple manuals.

Analyzes extracted JSON files and identifies:
- Data type mismatches
- Key ID mismatches (potential OCR errors)
- Description differences
- Scale/unit differences
- Enum/bitfield differences

Outputs a conflict report with suggested resolutions and confidence scores.
"""

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class KeyInstance:
    """A single extraction of a config key from one manual."""
    name: str
    key_id: str
    data_type: str
    description: str
    scale: str | None
    unit: str | None
    inline_enum: dict | None
    bitfield: dict | None
    source_file: str
    source_family: str
    source_version: str


@dataclass
class Conflict:
    """A detected conflict for a specific field."""
    field: str
    candidates: list[dict]  # [{value, sources, count}]
    suggested: Any
    confidence: float
    reason: str
    needs_human_review: bool


@dataclass
class KeyConflictReport:
    """Full conflict report for a single key."""
    key_id: str
    name: str
    instance_count: int
    conflicts: list[Conflict]
    sources: list[str]


def extract_manual_info(filename: str) -> tuple[str, str]:
    """Extract firmware family and version from filename."""
    match = re.match(r'u-blox-([A-Z0-9]+-[A-Z]+-[L0-9.]+)_', filename)
    if match:
        full_id = match.group(1)
        parts = full_id.rsplit('-', 1)
        if len(parts) == 2:
            return parts[0], parts[1]
    
    match = re.match(r'u-blox-([A-Z0-9-]+)-(\d+\.\d+)', filename)
    if match:
        return match.group(1), match.group(2)
    
    return "unknown", "unknown"


def load_all_keys(input_dir: Path) -> dict[str, list[KeyInstance]]:
    """Load all keys from extraction files, grouped by key_id."""
    keys_by_id: dict[str, list[KeyInstance]] = defaultdict(list)
    
    files = sorted(input_dir.glob("*_gemini_config_keys.json"))
    print(f"Loading {len(files)} extraction files...")
    
    for f in files:
        family, version = extract_manual_info(f.name)
        
        with open(f) as fp:
            data = json.load(fp)
        
        for key in data.get("keys", []):
            key_id = key.get("key_id", "")
            if not key_id:
                continue
            
            instance = KeyInstance(
                name=key.get("name", ""),
                key_id=key_id,
                data_type=key.get("data_type", ""),
                description=key.get("description", ""),
                scale=key.get("scale"),
                unit=key.get("unit"),
                inline_enum=key.get("inline_enum"),
                bitfield=key.get("bitfield"),
                source_file=f.name,
                source_family=family,
                source_version=version,
            )
            keys_by_id[key_id].append(instance)
    
    return keys_by_id


def compute_majority(values: list[tuple[Any, str]]) -> tuple[Any, list[dict], float]:
    """Compute majority vote for a list of (value, source) tuples.
    
    Returns (suggested_value, candidates_list, confidence).
    """
    if not values:
        return None, [], 0.0
    
    # Count occurrences
    counts: dict[Any, list[str]] = defaultdict(list)
    for value, source in values:
        # Normalize value for comparison
        if isinstance(value, dict):
            # For dicts (enum/bitfield), use JSON string for comparison
            key = json.dumps(value, sort_keys=True)
        else:
            key = value
        counts[key].append(source)
    
    # Build candidates list
    candidates = []
    for key, sources in counts.items():
        # Reconstruct original value
        # Handle case where key might be a number (float/int) instead of string
        key_str = str(key) if key is not None else ""
        if key_str.startswith('{'):
            try:
                value = json.loads(key_str)
            except:
                value = key
        else:
            value = key
        
        candidates.append({
            "value": value,
            "sources": sources,
            "count": len(sources),
        })
    
    # Sort by count descending
    candidates.sort(key=lambda x: x["count"], reverse=True)
    
    # Calculate confidence
    total = len(values)
    if candidates:
        confidence = candidates[0]["count"] / total
        suggested = candidates[0]["value"]
    else:
        confidence = 0.0
        suggested = None
    
    return suggested, candidates, confidence


def detect_conflicts_for_key(instances: list[KeyInstance]) -> KeyConflictReport | None:
    """Detect conflicts for a single key across all its instances."""
    if len(instances) < 2:
        return None
    
    key_id = instances[0].key_id
    conflicts = []
    
    # Check name consistency
    names = [(inst.name, f"{inst.source_family}-{inst.source_version}") for inst in instances]
    unique_names = set(n[0] for n in names)
    if len(unique_names) > 1:
        suggested, candidates, confidence = compute_majority(names)
        # High confidence name conflicts are usually OCR errors - auto-resolve
        conflicts.append(Conflict(
            field="name",
            candidates=candidates,
            suggested=suggested,
            confidence=confidence,
            reason="Key name mismatch - likely OCR/Unicode error" if confidence >= 0.75 else "Key name conflict",
            needs_human_review=confidence < 0.75,  # Only review low-confidence conflicts
        ))
    
    # Check data_type consistency
    types = [(inst.data_type, f"{inst.source_family}-{inst.source_version}") for inst in instances]
    unique_types = set(t[0] for t in types)
    if len(unique_types) > 1:
        suggested, candidates, confidence = compute_majority(types)
        # Check for known OCR patterns
        ocr_pattern = any(
            (c1.get("value") in ["I1", "I2", "I4", "I8"] and c2.get("value") in ["11", "12", "14", "18"])
            for c1 in candidates for c2 in candidates if c1 != c2
        )
        conflicts.append(Conflict(
            field="data_type",
            candidates=candidates,
            suggested=suggested,
            confidence=confidence,
            reason="Likely OCR error (I vs 1)" if ocr_pattern else "Data type mismatch",
            needs_human_review=confidence < 0.75,
        ))
    
    # Check scale consistency
    scales = [(inst.scale, f"{inst.source_family}-{inst.source_version}") for inst in instances if inst.scale]
    if scales:
        unique_scales = set(s[0] for s in scales)
        if len(unique_scales) > 1:
            suggested, candidates, confidence = compute_majority(scales)
            # Prefer non-dash values over "-" (dash means N/A)
            non_dash = [c for c in candidates if c["value"] != "-"]
            if non_dash and suggested == "-":
                suggested = non_dash[0]["value"]
                confidence = 0.9  # High confidence for preferring actual value
            conflicts.append(Conflict(
                field="scale",
                candidates=candidates,
                suggested=suggested,
                confidence=confidence,
                reason="Scale value differs - prefer actual value over '-'" if any(c["value"] == "-" for c in candidates) else "Scale value differs",
                needs_human_review=confidence < 0.75,
            ))
    
    # Check unit consistency
    units = [(inst.unit, f"{inst.source_family}-{inst.source_version}") for inst in instances if inst.unit]
    if units:
        unique_units = set(u[0] for u in units)
        if len(unique_units) > 1:
            suggested, candidates, confidence = compute_majority(units)
            # Prefer non-dash values over "-" (dash means N/A)
            non_dash = [c for c in candidates if c["value"] != "-"]
            if non_dash and suggested == "-":
                suggested = non_dash[0]["value"]
                confidence = 0.9
            conflicts.append(Conflict(
                field="unit",
                candidates=candidates,
                suggested=suggested,
                confidence=confidence,
                reason="Unit differs - prefer actual value over '-'" if any(c["value"] == "-" for c in candidates) else "Unit differs",
                needs_human_review=confidence < 0.75,
            ))
    
    # Check enum completeness (not strict conflict - merge superset)
    enums = [inst.inline_enum for inst in instances if inst.inline_enum]
    if len(enums) > 1:
        # Check if enums differ
        enum_strs = set(json.dumps(e, sort_keys=True) for e in enums)
        if len(enum_strs) > 1:
            # Build merged superset
            merged_values = {}
            for enum in enums:
                if "values" in enum:
                    vals = enum["values"]
                    # Handle both dict and list formats
                    if isinstance(vals, dict):
                        merged_values.update(vals)
                    elif isinstance(vals, list):
                        # Convert list of {name, value, description} to dict
                        for item in vals:
                            if isinstance(item, dict) and "name" in item:
                                merged_values[item["name"]] = item
            
            conflicts.append(Conflict(
                field="inline_enum",
                candidates=[{"value": e, "sources": ["merged"], "count": 1} for e in enums[:3]],  # Sample
                suggested={"values": merged_values},
                confidence=1.0,  # Superset merge is deterministic
                reason="Enum values differ - merged superset",
                needs_human_review=False,
            ))
    
    # Check bitfield completeness (not strict conflict - merge superset)
    bitfields = [inst.bitfield for inst in instances if inst.bitfield]
    if len(bitfields) > 1:
        bf_strs = set(json.dumps(b, sort_keys=True) for b in bitfields)
        if len(bf_strs) > 1:
            # Merge bitfield bits
            all_bits = {}
            for bf in bitfields:
                for bit in bf.get("bits", []):
                    bit_key = f"{bit.get('bit_start')}-{bit.get('bit_end')}"
                    if bit_key not in all_bits:
                        all_bits[bit_key] = bit
            
            conflicts.append(Conflict(
                field="bitfield",
                candidates=[{"value": "varies", "sources": ["multiple"], "count": len(bitfields)}],
                suggested={"bits": list(all_bits.values())},
                confidence=1.0,
                reason="Bitfield definitions differ - merged superset",
                needs_human_review=False,
            ))
    
    if not conflicts:
        return None
    
    return KeyConflictReport(
        key_id=key_id,
        name=instances[0].name,  # Use first instance name
        instance_count=len(instances),
        conflicts=conflicts,
        sources=[f"{inst.source_family}-{inst.source_version}" for inst in instances],
    )


def generate_report(keys_by_id: dict[str, list[KeyInstance]], output_file: Path):
    """Generate conflict report."""
    
    all_conflicts: list[KeyConflictReport] = []
    adjudication_queue: list[dict] = []
    
    print("Detecting conflicts...")
    for key_id, instances in keys_by_id.items():
        report = detect_conflicts_for_key(instances)
        if report:
            all_conflicts.append(report)
            
            # Add to adjudication queue if needed
            for conflict in report.conflicts:
                if conflict.needs_human_review:
                    adjudication_queue.append({
                        "key_id": key_id,
                        "key_name": report.name,
                        "field": conflict.field,
                        "candidates": conflict.candidates,
                        "suggested": conflict.suggested,
                        "confidence": conflict.confidence,
                        "reason": conflict.reason,
                        "decision": None,
                    })
    
    # Summary statistics
    total_keys = len(keys_by_id)
    keys_with_conflicts = len(all_conflicts)
    total_conflicts = sum(len(r.conflicts) for r in all_conflicts)
    needs_review = len(adjudication_queue)
    
    # Group conflicts by type
    conflicts_by_type: dict[str, int] = defaultdict(int)
    for report in all_conflicts:
        for conflict in report.conflicts:
            conflicts_by_type[conflict.field] += 1
    
    # Build output
    output = {
        "summary": {
            "total_keys": total_keys,
            "keys_with_conflicts": keys_with_conflicts,
            "total_conflicts": total_conflicts,
            "needs_human_review": needs_review,
            "auto_resolvable": total_conflicts - needs_review,
        },
        "conflicts_by_type": dict(conflicts_by_type),
        "conflicts": [
            {
                "key_id": r.key_id,
                "name": r.name,
                "instance_count": r.instance_count,
                "sources": r.sources,
                "conflicts": [
                    {
                        "field": c.field,
                        "candidates": c.candidates,
                        "suggested": c.suggested,
                        "confidence": c.confidence,
                        "reason": c.reason,
                        "needs_human_review": c.needs_human_review,
                    }
                    for c in r.conflicts
                ],
            }
            for r in all_conflicts
        ],
    }
    
    # Write main report
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as fp:
        json.dump(output, fp, indent=2)
    
    # Write adjudication queue if needed
    if adjudication_queue:
        adj_file = output_file.parent / "adjudication_queue.json"
        with open(adj_file, "w") as fp:
            json.dump({"items": adjudication_queue}, fp, indent=2)
        print(f"Adjudication queue: {adj_file}")
    
    # Print summary
    print(f"\nConflict Detection Summary:")
    print(f"  Total keys: {total_keys}")
    print(f"  Keys with conflicts: {keys_with_conflicts}")
    print(f"  Total conflicts: {total_conflicts}")
    print(f"  Auto-resolvable: {total_conflicts - needs_review}")
    print(f"  Needs human review: {needs_review}")
    print(f"\nConflicts by type:")
    for field, count in sorted(conflicts_by_type.items()):
        print(f"  {field}: {count}")
    print(f"\nReport written to: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Detect conflicts in config key extractions")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/config_keys/by-manual"),
        help="Directory containing extracted JSON files",
    )
    parser.add_argument(
        "--output-report",
        type=Path,
        default=Path("data/config_keys/conflict_report.json"),
        help="Output file for conflict report",
    )
    args = parser.parse_args()
    
    keys_by_id = load_all_keys(args.input_dir)
    generate_report(keys_by_id, args.output_report)


if __name__ == "__main__":
    main()
