# Bitfield Extraction Workflow

Extract and fix missing bitfield definitions in the UBX message schema.

## Overview

Bitfields are packed bit definitions for X-type fields (X1, X2, X4). When new messages are added or the schema is incomplete, bitfield definitions may be missing. This workflow extracts them from PDF manuals using LLM-based extraction.

## Prerequisites

- Google API key: `export GOOGLE_API_KEY="your-key"`
- PDF manuals in `interface_manuals/`

## Quick Start

### Fix a Single Message

```bash
# Check what's missing
uv run python validation/scripts/validate_message.py UBX-NAV-PVT --extract-missing

# Extract and apply
uv run python validation/scripts/validate_message.py UBX-NAV-PVT --extract-missing --apply
```

### Fix All Messages with Missing Bitfields

```bash
# Preview what would be fixed
uv run python validation/scripts/validate_all_messages.py --fix-bitfields --dry-run

# Fix all missing bitfields (uses Gemini API)
uv run python validation/scripts/validate_all_messages.py --fix-bitfields

# Parallel processing (faster, higher API cost)
uv run python validation/scripts/validate_all_messages.py --fix-bitfields --workers 3
```

## Detailed Workflow

### Step 1: Identify Missing Bitfields

```bash
# Generate coverage report
uv run python scripts/generate_coverage_report.py

# Or check specific message
uv run python validation/scripts/validate_message.py UBX-NAV-SAT -v
```

The coverage report (`COVERAGE.md`) shows:
- Total X-type fields: 173
- Fields with bitfield definitions: 159 (92%)
- Fields missing bitfields by reason (reserved, protocol-specific, etc.)

### Step 2: Extract from PDF

The extraction process:
1. Finds the message in PDF table of contents
2. Extracts relevant pages to temporary PDF
3. Sends to Gemini API with extraction prompt
4. Parses structured bitfield data

```bash
# Extract without applying (for review)
uv run python validation/scripts/validate_message.py UBX-CFG-NAV5 --extract-missing
```

Output shows:
- Fields missing bitfields
- Extraction confidence
- Source manual used

### Step 3: Apply to Schema

```bash
# Apply extracted bitfields
uv run python validation/scripts/validate_message.py UBX-CFG-NAV5 --extract-missing --apply
```

This modifies `data/messages/ubx_messages.json` directly.

### Step 4: Verify

```bash
# Run tests
uv run pytest testing/tests/ -v

# Regenerate coverage report
uv run python scripts/generate_coverage_report.py
```

## Batch Processing

For fixing multiple messages efficiently:

```bash
# Fix all messages with missing bitfields
uv run python validation/scripts/validate_all_messages.py --fix-bitfields

# Limit to specific count (useful for testing)
uv run python validation/scripts/validate_all_messages.py --fix-bitfields --limit 5

# With delay between API calls (rate limiting)
uv run python validation/scripts/validate_all_messages.py --fix-bitfields --delay 3.0
```

## Cost Estimates

- Single message extraction: ~$0.01-0.05 (depends on PDF pages)
- Full batch (all missing): ~$0.50-2.00

The extraction prioritizes F9 HPG 1.51 manual (best documentation quality).

## Troubleshooting

### "Not found in any manual"

The message may not be documented in available PDFs. Check:
- Is the message in legacy-only manuals (M8)?
- Is it a newer protocol version not yet in our PDFs?

### Low confidence extractions

Review manually before applying. The extraction adds confidence level:
- `high` - Clear table with bit definitions
- `medium` - Text description parsed
- `low` - Partial or ambiguous data

### API rate limits

Use `--delay` flag to add pause between requests:
```bash
uv run python validation/scripts/validate_all_messages.py --fix-bitfields --delay 5.0
```

## Technical Details

### Bitfield Schema Format

```json
{
  "name": "flags",
  "data_type": "X2",
  "bitfield": [
    {"name": "gnssFixOK", "bit_offset": 0, "bit_width": 1, "description": "Valid fix"},
    {"name": "diffSoln", "bit_offset": 1, "bit_width": 1, "description": "Differential corrections applied"},
    {"name": "reserved", "bit_offset": 2, "bit_width": 3, "description": "Reserved"}
  ]
}
```

### Scripts Reference

| Script | Purpose |
|--------|---------|
| `validation/scripts/validate_message.py` | Single message validation and extraction |
| `validation/scripts/validate_all_messages.py` | Batch validation and extraction |
| `scripts/generate_coverage_report.py` | Generate COVERAGE.md with statistics |

### API Functions

```python
from validation.scripts.validate_message import (
    extract_missing_bitfields,
    apply_extracted_bitfields,
    find_missing_bitfields,
)

# Extract without applying
result = extract_missing_bitfields("UBX-NAV-PVT", verbose=True)

# Apply separately
if result.get("fields"):
    apply_extracted_bitfields("UBX-NAV-PVT", result["fields"])
```
