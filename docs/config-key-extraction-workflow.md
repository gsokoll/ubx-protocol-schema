# Config Key Extraction Workflow

## Overview

Extract UBX configuration keys from u-blox PDF interface manuals using Google Gemini API, then validate, resolve conflicts, and merge into a unified schema-compliant database.

## Scripts

| Script | Purpose |
|--------|---------|
| `extract_config_keys_with_gemini.py` | Extract keys from PDF using Gemini |
| `detect_config_key_conflicts.py` | Detect conflicts across extractions |
| `adjudicate_config_keys.py` | Resolve conflicts using LLM |
| `merge_config_keys.py` | Merge into unified schema-compliant database |

## Quick Start

```bash
# 1. Extract config keys from a manual
export GOOGLE_API_KEY="your-key"
uv run python scripts/extract_config_keys_with_gemini.py --pdf-path <manual.pdf>

# 2. Run conflict detection across all extractions
uv run python scripts/detect_config_key_conflicts.py

# 3. Resolve conflicts with LLM (or review manually)
uv run python scripts/adjudicate_config_keys.py

# 4. Merge into unified database (auto-applies schema fixes)
uv run python scripts/merge_config_keys.py
```

## Files

- **Schema**: `schema/ubx-config-keys-schema.json`
- **Per-manual extractions**: `data/config_keys/by-manual/*.json`
- **Conflict report**: `data/config_keys/conflict_report.json`
- **Adjudication queue**: `data/config_keys/adjudication_queue.json`
- **Final output**: `data/config_keys/unified_config_keys.json`

## Phase 1: Extraction (Current)

### How It Works

1. **TOC Discovery**: Parse PDF table of contents to find:
   - Intro pages (Configuration interface sections 6.1-6.8)
   - Per-group page ranges (CFG-XXX sections in 6.9)

2. **Batch by Page Count**: Group consecutive CFG-XXX groups into batches (~15 pages max) to stay within Gemini output token limits while minimizing API calls.

3. **PDF Assembly**: For each batch, create a PDF containing:
   - Intro pages (data types, layers, etc. for context)
   - Content pages for the groups in that batch

4. **Gemini Extraction**: Upload PDF and prompt Gemini to extract:
   - Key name, key_id, data_type, description
   - Scale and unit (if applicable)
   - Inline enums with values and descriptions
   - Bitfield definitions

5. **OCR Fix**: Post-process to fix known OCR errors (e.g., `I2C` → `12C`)

6. **Deduplication**: Remove duplicate keys within each manual

### Commands

```bash
# Dry run - preview batches without extraction
uv run python scripts/extract_config_keys_with_gemini.py \
  --pdf-path interface_manuals/zed-f9p-module/u-blox-F9-HPG-1.51_InterfaceDescription_UBXDOC-963802114-13124.pdf \
  --dry-run

# Full extraction
uv run python scripts/extract_config_keys_with_gemini.py \
  --pdf-path <pdf-path>

# Extract specific groups only
uv run python scripts/extract_config_keys_with_gemini.py \
  --pdf-path <pdf-path> \
  --groups CFG-RATE CFG-NMEA

# Adjust batch size
uv run python scripts/extract_config_keys_with_gemini.py \
  --pdf-path <pdf-path> \
  --max-pages 20
```

### Cost Estimate

- ~$0.03 per manual (4 batches × ~$0.007/batch)
- 21 manuals total = ~$0.60-1.00

## Phase 2: Conflict Detection

### Overview

Programmatically detect conflicts across extractions before merging. Conflicts indicate either:
- Extraction errors (OCR, LLM hallucination)
- Legitimate differences (key changed between firmware versions)

### Conflict Types

| Type | Fields | Auto-Resolvable? |
|------|--------|------------------|
| **Data type mismatch** | `data_type` | Yes - majority vote |
| **Key ID mismatch** | `key_id` | No - likely OCR error, needs review |
| **Description differs** | `description` | Yes - prefer longest/latest |
| **Scale/unit differs** | `scale`, `unit` | Yes - majority vote |
| **Enum values differ** | `inline_enum` | Yes - merge superset |
| **Bitfield differs** | `bitfield` | Yes - merge superset |
| **Key missing** | (presence) | N/A - track version support |

### Detection Script: `detect_config_key_conflicts.py`

```bash
uv run python scripts/detect_config_key_conflicts.py \
  --input-dir data/config_keys/by-manual \
  --output-report data/config_keys/conflict_report.json
```

**Output**: JSON report with:
- Keys with conflicts (grouped by conflict type)
- Per-key: all differing values with source manuals
- Suggested resolution (majority vote result)
- Confidence score (agreement percentage)

### Resolution Rules (Programmatic)

1. **High confidence** (≥75%): Auto-accept
2. **Low confidence** (<75%): Requires human adjudication

The 75% threshold balances automation with accuracy. Most NAV vs NAV2 confusion errors are caught at this threshold.

## Phase 3: Conflict Resolution & Merge

### Step 3.1: Auto-Resolution

For conflicts meeting auto-resolution criteria:
- Apply majority vote for scalar fields
- Merge superset for enum/bitfield data
- Prefer latest firmware version for ties

### Step 3.2: Human Adjudication Queue

Generate `adjudication_queue.json` with conflicts requiring human review:
- Key name/ID mismatches (potential OCR errors)
- No-majority conflicts
- Suspicious patterns (e.g., value only in one extraction)

**Adjudication format**:
```json
{
  "key_id": "0x10240001",
  "field": "data_type",
  "candidates": [
    {"value": "I4", "sources": ["F9-HPG-1.51", "F9-HPG-1.50"], "count": 2},
    {"value": "14", "sources": ["X20-HPG-2.00"], "count": 1}
  ],
  "suggested": "I4",
  "reason": "Likely OCR error (I vs 1)",
  "decision": null  // Human fills this in
}
```

### Step 3.3: Merge with Schema Compliance

```bash
uv run python scripts/merge_config_keys.py
```

The merge script automatically:
- Adds `group` field (extracted from key name)
- Adds `item_id` field (extracted from key_id bits 15-0)
- Builds `groups` object with group_id from key_id bits 23-16
- Converts `scale` strings to objects: `"1e-7"` → `{"raw": "1e-7", "multiplier": 1e-7}`
- Removes `None` values from optional fields
- Cleans invalid units (`"-"`, `" "`, `"1"`)
- Fixes inline_enum format (list → dict, removes None values)
- Adds missing `data_type` to bitfield entries
- Pads key_id to 8 hex digits
- **Validates against schema** at the end

Output shows: `✓ Schema validation: PASSED`

## Phase 4: Version Tracking

### Per-Key Metadata

Each key in unified database includes:
```json
{
  "name": "CFG-RATE-MEAS",
  "key_id": "0x30210001",
  "_sources": {
    "families": ["F9-HPG", "F9-HPS", "M9-SPG"],
    "versions": ["F9-HPG-1.51", "F9-HPS-1.40", "M9-SPG-4.04"],
    "first_seen": "F9-HPG-1.13",
    "deprecated_in": null
  },
  "_confidence": {
    "data_type": 1.0,
    "description": 0.85,
    "enum_complete": true
  }
}
```

## Phase 5: Code Generation (Future)

### Potential Outputs

- Rust structs/enums for config keys
- C header files
- Python dataclasses
- Documentation

## Manuals with Config Keys

| Family | Manual | Groups | Batches |
|--------|--------|--------|---------|
| F9-HPG | 1.51 | 39 | 4 |
| F9-HPG | 1.50 | 39 | 4 |
| F9-HPG | 1.32 | 39 | 4 |
| F9-HPS | 1.40 | 38 | 4 |
| F9-HPS | 1.30 | 38 | 4 |
| F9-LAP | 1.50 | 35 | 4 |
| F9-LAP | 1.30 | 36 | 4 |
| F9-DBD | 1.30 | 35 | 4 |
| M9-SPG | 4.04 | 36 | 4 |
| M9-MDR | 2.16 | 36 | 4 |
| M10-SPG | 5.30 | 31 | 3 |
| M10-SPG | 5.10 | 29 | 3 |
| F10-SPG | 6.00 | 28 | 3 |
| X20-HPG | 2.02 | 38 | 4 |
| X20-HPG | 2.00 | 35 | 4 |

## Known Issues & Mitigations

### OCR Errors (Auto-Fixed)

Gemini renders PDFs to images internally, causing occasional OCR errors:

| Error | Correct | Fix |
|-------|---------|-----|
| `CFG-12C*` | `CFG-I2C*` | Post-processing |
| `CFG-0DO` | `CFG-ODO` | Post-processing |
| `_ENNA` | `_ENA` | Post-processing |
| `14` (data type) | `I4` | Post-processing |
| Space in name | Underscore | Post-processing |
| `S` (unit) | `s` | Post-processing |

### NAV vs NAV2 Confusion

Gemini sometimes confuses adjacent NAV and NAV2 keys in CFG-MSGOUT tables. 
- **Mitigation**: Explicit prompt warning + 75% confidence threshold catches most errors
- **Resolution**: ~114 auto-resolved, ~20 require manual review

### Table Structure Variation

Some older manuals (M9-SPG, M9-MDR, X20-HPG) have 5-column tables (no Scale column) instead of 6-column.
- **Mitigation**: Prompt warns about this, post-processing detects unit-in-scale-column errors

### Large Groups

CFG-MSGOUT is ~22 pages, exceeding the default 15-page batch limit. It gets its own batch automatically.

## Statistics (21 Manuals)

| Metric | Value |
|--------|-------|
| Total unique keys | 1,063 |
| Groups | 47 |
| Keys with enums | 57 |
| Keys with bitfields | 17 |
| Keys with scale | 52 |
| Keys with unit | 110 |
| Extraction cost | ~$0.60 |

## Notes

- Gemini 2.5 Flash-Lite is cost-effective (~$0.10/M input, $0.40/M output)
- Native PDF upload, but Gemini still does internal image rendering
- Structured JSON output via `response_mime_type="application/json"`
- Schema validation runs automatically at merge time
