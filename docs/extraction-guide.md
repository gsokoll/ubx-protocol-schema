# UBX Message Extraction Guide

This guide explains how to extract UBX protocol message definitions from u-blox PDF manuals.

## Prerequisites

1. **Python 3.10+** with `uv` package manager
2. **Anthropic API key** for Claude-based extraction
3. **PDF manual** from u-blox (or URL to download)

## Quick Start

```bash
# Set your API key
export ANTHROPIC_API_KEY=your_key_here

# Extract all messages from a local PDF
uv run python scripts/extract_with_anthropic.py \
  --pdf interface_manuals/your-manual.pdf \
  --all-messages
```

## Extraction Methods

### Method 1: Extract from Local PDF (Recommended)

```bash
uv run python scripts/extract_with_anthropic.py \
  --pdf interface_manuals/F9-HPG-1.51/u-blox-F9-HPG-1.51_InterfaceDescription.pdf \
  --all-messages
```

### Method 2: Extract from URL

```bash
uv run python scripts/extract_with_anthropic.py \
  --pdf-url "https://content.u-blox.com/.../manual.pdf" \
  --all-messages
```

The PDF will be downloaded and cached locally.

### Method 3: Extract Specific Message

```bash
uv run python scripts/extract_with_anthropic.py \
  --pdf interface_manuals/your-manual.pdf \
  --message UBX-NAV-PVT
```

### Method 4: Re-extract with Force

To re-extract a message that was previously cached:

```bash
uv run python scripts/extract_with_anthropic.py \
  --pdf interface_manuals/your-manual.pdf \
  --message UBX-NAV-PVT \
  --force
```

## Output Format

Extractions are saved to `data/by-manual/<manual-name>_anthropic.json`:

```json
{
  "source": {
    "pdf_path": "interface_manuals/...",
    "extraction_date": "2025-12-28",
    "prompt_version": "1.2"
  },
  "messages": [
    {
      "name": "UBX-NAV-PVT",
      "class_id": "0x01",
      "message_id": "0x07",
      "message_type": "output",
      "description": "Navigation position velocity time solution",
      "payload": {
        "length": {"fixed": 92},
        "fields": [
          {
            "name": "iTOW",
            "byte_offset": 0,
            "data_type": "U4",
            "size_bytes": 4,
            "unit": "ms",
            "description": "GPS time of week"
          }
        ]
      }
    }
  ]
}
```

## Validation Pipeline

After extraction, validate using majority voting:

```bash
# Run validation with verbose output
uv run python scripts/validate_majority.py \
  --extractions-dir data/by-manual \
  --verbose
```

This produces:
- `analysis_reports/validation_report.json` — Consensus results per message
- `analysis_reports/discrepancy_report.json` — Outliers and differences
- `data/validated/messages/*.json` — Canonical message definitions

## Re-extraction of Outliers

When validation identifies extraction errors (outliers), re-extract them:

```bash
# Re-extract all outliers with consensus context
uv run python scripts/reextract_outliers.py
```

The script:
1. Reads `analysis_reports/discrepancy_report.json` for outlier list
2. Re-extracts each outlier from its source PDF
3. Provides Claude with consensus fields as reference
4. Updates the extraction file with corrected result

For version-variant messages (e.g., MON-GNSS, NAV-RELPOSNED):

```bash
uv run python scripts/reextract_version_messages.py
```

## Prompt Hints

Complex messages have hints in `src/extraction/prompts.py`:

- **SHORT_HINTS**: Brief guidance appended to standard prompt
- **DEDICATED_PROMPTS**: Complete replacement prompts for challenging messages
- **ENUM_GUIDANCE**: Hints for fields with enumeration values

Add hints when a message consistently fails extraction.

## Adjudication (No-Consensus Messages)

When validation shows messages without consensus due to protocol evolution:

```bash
# Generate difference reports
uv run python scripts/generate_adjudication_reports.py

# Review reports in analysis_reports/adjudication/
# Update data/validated/protocol_notes.json with decision

# Generate validated JSON for adjudicated messages
uv run python scripts/generate_adjudicated_messages.py
```

See `data/validated/protocol_notes.json` for documented protocol inconsistencies.

## Troubleshooting

### "Message not found in PDF TOC"

The extraction uses PDF table of contents to locate messages. If not found:
1. Check if the message exists in that manual version
2. The TOC parsing may have failed — check PDF structure

### "API rate limit exceeded"

The Anthropic API has rate limits. Solutions:
- Wait and retry
- Use `--use-cache` to skip already-extracted messages
- Extract fewer messages per run

### "Extraction quality issues"

If fields are missing or incorrect:
1. Check `analysis_reports/discrepancy_report.json` for known issues
2. Add prompt hints to `src/extraction/prompts.py`
3. Re-extract the message with `--force`

## Cost Estimation

Extraction costs depend on PDF size and message count:

| Manual Size | Messages | Estimated Cost |
|-------------|----------|----------------|
| Small (100 pages) | ~50 | ~$1.50 |
| Medium (200 pages) | ~100 | ~$3.00 |
| Large (300+ pages) | ~150 | ~$5.00 |

**Total for all 34 manuals**: ~$100-150

## Complete Workflow

To add a new manual to the repository:

```bash
# 1. Add URL to interface_manuals/manuals.json

# 2. Download the PDF
uv run python scripts/download_manuals.py

# 3. Extract all messages
export ANTHROPIC_API_KEY=your_key
uv run python scripts/extract_with_anthropic.py \
  --pdf interface_manuals/your-manual.pdf \
  --all-messages

# 4. Run validation
uv run python scripts/validate_majority.py \
  --extractions-dir data/by-manual \
  --verbose

# 5. Re-extract outliers if needed
uv run python scripts/reextract_outliers.py

# 6. Re-run validation to confirm
uv run python scripts/validate_majority.py \
  --extractions-dir data/by-manual \
  --verbose

# 7. Commit changes
git add data/
git commit -m "feat: add extraction for <manual-name>"
```
