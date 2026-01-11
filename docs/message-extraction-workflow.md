# UBX Message Extraction Workflow

## Overview

This document describes the workflows for maintaining and extending the UBX message schema. There are two primary workflows:

1. **Adding a new manual** - When u-blox releases new firmware/products
2. **Fixing existing messages** - Correcting bitfields, fields, or other issues

## Prerequisites

- Python 3.10+ with `uv` package manager
- API key for extraction:
  - `GOOGLE_API_KEY` for Gemini API (primary)
  - `ANTHROPIC_API_KEY` for Anthropic API (alternative)

## Workflow 1: Adding a New Manual

Use this when u-blox releases a new interface description PDF.

### Quick Start

```bash
# Single command to process a new manual
uv run python scripts/add_manual.py --pdf-path interface_manuals/new-device/manual.pdf

# Or preview what would be extracted (dry-run)
uv run python scripts/add_manual.py --dry-run
```

### Manual Steps (if not using orchestrator)

#### Step 1: Add PDF to repository

Place the PDF in `interface_manuals/<device-family>/`:

```
interface_manuals/
  neo-m9n-module/
    u-blox-M9-SPG-4.04_InterfaceDescription_xxx.pdf  <- new file
```

Optionally update `interface_manuals/manuals.json` for tracking.

#### Step 2: Build inventory

Scan all PDFs to discover messages:

```bash
uv run python validation/scripts/build_inventory.py
```

Output: `validation/inventory/pdf_inventory.json`

#### Step 3: Run gap analysis

Compare inventory against current schema:

```bash
uv run python validation/scripts/gap_analysis.py
```

This shows:
- **MISSING**: Messages in PDFs but not in schema
- **ORPHANED**: Messages in schema but not in any PDF
- Coverage statistics per manual

#### Step 4: Extract missing messages

```bash
# List missing messages
uv run python validation/scripts/extract_missing.py --list

# Extract all missing messages
uv run python validation/scripts/extract_missing.py --all

# Extract specific message
uv run python validation/scripts/extract_missing.py UBX-NAV2-CLOCK
```

Extracted messages are saved to `data/preliminary/extracted_missing/`.

#### Step 5: Merge into schema

```bash
# Preview changes
uv run python validation/scripts/merge_extracted.py --dry-run

# Apply changes
uv run python validation/scripts/merge_extracted.py
```

#### Step 6: Generate coverage report

```bash
uv run python scripts/generate_coverage_report.py
```

Updates `COVERAGE.md` with current statistics.

#### Step 7: Validate and test

```bash
# Run cross-validation against pyubx2
uv run python validation/scripts/cross_validate.py --summary

# Run tests
uv run pytest testing/tests/ -v
```

## Workflow 2: Fixing Existing Messages

Use this to fix missing bitfields, incorrect fields, or other schema issues.

### Single Message Fix

```bash
# Validate a message and show issues
uv run python validation/scripts/validate_message.py UBX-NAV-PVT -v

# Extract missing bitfield definitions from PDFs
uv run python validation/scripts/validate_message.py UBX-NAV-PVT --extract-missing

# Extract AND apply fixes to schema
uv run python validation/scripts/validate_message.py UBX-NAV-PVT --extract-missing --apply
```

### Batch Fix (all messages)

```bash
# Fix all messages with missing bitfields
uv run python validation/scripts/validate_all_messages.py --fix-bitfields

# Fix all issues (bitfields + other problems)
uv run python validation/scripts/validate_all_messages.py --fix-all --workers 2
```

### Cross-Validation

Compare schema against pyubx2 library:

```bash
# Summary of differences
uv run python validation/scripts/cross_validate.py --summary

# Detailed comparison for specific message
uv run python validation/scripts/cross_validate.py UBX-NAV-PVT -v

# Save results to file
uv run python validation/scripts/cross_validate.py --all --save
```

## Scripts Reference

### Main Workflow Scripts

| Script | Purpose |
|--------|---------|
| `scripts/add_manual.py` | Orchestrator for adding new manuals |
| `validation/scripts/build_inventory.py` | Build message inventory from PDF TOCs |
| `validation/scripts/gap_analysis.py` | Compare inventory vs schema |
| `validation/scripts/extract_missing.py` | Extract missing messages from PDFs |
| `validation/scripts/merge_extracted.py` | Merge extracted messages into schema |
| `validation/scripts/validate_message.py` | Validate single message, extract/apply fixes |
| `validation/scripts/validate_all_messages.py` | Batch validation and fixing |
| `validation/scripts/cross_validate.py` | Compare against pyubx2 |
| `scripts/generate_coverage_report.py` | Generate COVERAGE.md |

### Bulk Extraction Scripts (Historical)

These scripts were used for initial bulk extraction. For ongoing maintenance, use the validation scripts above.

| Script | Purpose |
|--------|---------|
| `scripts/bulk_extraction/extract_messages_v2.py` | Multi-stage message extraction |
| `scripts/bulk_extraction/vote_preliminary_v2.py` | Voting on extractions |
| `scripts/bulk_extraction/final_determination_v2.py` | Final determination |
| `scripts/bulk_extraction/run_workflow_v2.py` | Orchestrates full extraction |
| `scripts/bulk_extraction/generate_message_collection.py` | Generate final JSON from adjudication |

## Data Flow

```
interface_manuals/*.pdf
        |
        v
[build_inventory.py]
        |
        v
validation/inventory/pdf_inventory.json (ground truth)
        |
        v
[gap_analysis.py]
        |
        v
validation/reports/gap_analysis.json (what's missing)
        |
        v
[extract_missing.py] <-- Gemini API
        |
        v
data/preliminary/extracted_missing/*.json
        |
        v
[merge_extracted.py]
        |
        v
data/messages/ubx_messages.json (canonical schema)
        |
        v
[generate_coverage_report.py]
        |
        v
COVERAGE.md
```

## Output Files

| File | Description |
|------|-------------|
| `data/messages/ubx_messages.json` | Canonical message definitions (239 messages) |
| `data/messages/enumerations.json` | Enumeration definitions |
| `data/config_keys/unified_config_keys.json` | Configuration keys |
| `data/manual_metadata.json` | Manual-to-protocol version mapping |
| `validation/inventory/pdf_inventory.json` | Message inventory from PDFs |
| `validation/reports/gap_analysis.json` | Gap analysis results |
| `COVERAGE.md` | Coverage statistics |

## Troubleshooting

### API rate limits

If you hit API rate limits, use `--workers 1` for serial processing:

```bash
uv run python validation/scripts/validate_all_messages.py --fix-bitfields --workers 1
```

### Missing manual metadata

If `merge_extracted.py` can't find protocol versions, update `data/manual_metadata.json`:

```bash
uv run python scripts/bulk_extraction/extract_manual_metadata.py
```

### Extraction quality issues

If LLM extraction produces poor results:

1. Try a different manual (some PDFs have better OCR)
2. Use `--manual` flag to specify a known-good manual
3. Check `src/extraction/prompts.py` for message-specific hints

## See Also

- [Bitfield Extraction Workflow](bitfield-extraction-workflow.md) - Fixing missing bitfield definitions
- [Enumeration Extraction Workflow](enumeration-extraction-workflow.md) - Validating enumerations
- [Config Key Extraction Workflow](config-key-extraction-workflow.md) - Config key extraction
- [Schema Design Notes](schema-design-notes.md) - Schema design decisions
