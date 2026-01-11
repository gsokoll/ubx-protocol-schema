# Enumeration Extraction Workflow

Extract and validate enumeration definitions for UBX protocol fields.

## Overview

Enumerations define the meaning of integer values for specific fields (e.g., `fixType`: 0=no fix, 1=2D, 2=3D). This workflow handles:
1. **Extraction** - Parse enum values from field descriptions
2. **Validation** - Compare against PDF manuals using LLM

## Data Location

- Canonical enumerations: `data/messages/enumerations.json`
- Currently 23 enumeration definitions

## Prerequisites

For validation:
- Google API key: `export GOOGLE_API_KEY="your-key"`
- PDF manuals in `interface_manuals/`

## Scripts Reference

| Script | Purpose |
|--------|---------|
| `scripts/bulk_extraction/extract_enumerations.py` | Extract enums from field descriptions |
| `validation/scripts/validate_enumerations.py` | Validate enums against PDFs |

## Workflow 1: Extract Enumerations from Schema

The extraction script parses enum-like patterns from field descriptions:
- `"0 = no fix, 1 = 2D-fix, 2 = 3D-fix"`
- `"0x01 = Dead Reckoning, 0x02 = 2D-Fix"`

```bash
# Generate report of all extracted enumerations
uv run python scripts/bulk_extraction/extract_enumerations.py --report

# Output canonical enumerations to file
uv run python scripts/bulk_extraction/extract_enumerations.py --output data/messages/enumerations.json

# Apply enumerations back to message definitions
uv run python scripts/bulk_extraction/extract_enumerations.py --apply
```

### Extraction Process

1. Scans all message JSON files in `data/messages/`
2. Parses field descriptions for enum patterns
3. Normalizes value names to snake_case
4. Merges values across messages (same field in multiple messages)
5. Outputs canonical definitions

## Workflow 2: Validate Against PDFs

Validate that enumeration values match the PDF documentation.

```bash
# List all available enumerations
uv run python validation/scripts/validate_enumerations.py --list

# Validate a specific enumeration
uv run python validation/scripts/validate_enumerations.py fixType

# Validate all enumerations
uv run python validation/scripts/validate_enumerations.py --all
```

### How Validation Works

1. Looks up the enumeration in `enumerations.json`
2. Finds associated message(s) via `ENUM_MESSAGE_MAP`
3. Extracts relevant PDF pages
4. Uses Gemini to compare canonical vs PDF values
5. Reports discrepancies

### The ENUM_MESSAGE_MAP

Located in `validation/scripts/validate_enumerations.py`, this maps enumerations to the messages where they appear:

```python
ENUM_MESSAGE_MAP = {
    "timeRef": ["UBX-CFG-RATE", "UBX-CFG-TP5"],
    "fixType": ["UBX-NAV-PVT", "UBX-NAV-STATUS"],
    "gnssId": ["UBX-NAV-SAT", "UBX-NAV-SIG", "UBX-MON-GNSS"],
    # ...
}
```

**When adding new enumerations**, update this map to enable validation.

## Adding New Enumerations

### Option 1: From Existing Field Descriptions

If the enumeration is already described in field descriptions:

```bash
# Re-run extraction to pick up new patterns
uv run python scripts/bulk_extraction/extract_enumerations.py --report

# Review and apply
uv run python scripts/bulk_extraction/extract_enumerations.py --output data/messages/enumerations.json
```

### Option 2: Manual Addition

Edit `data/messages/enumerations.json` directly:

```json
{
  "newEnum": {
    "type": "U1",
    "values": [
      {"value": 0, "name": "disabled", "description": "Feature disabled"},
      {"value": 1, "name": "enabled", "description": "Feature enabled"}
    ],
    "occurrences": 1,
    "messages": ["UBX-NEW-MSG"]
  }
}
```

Then update `ENUM_MESSAGE_MAP` in the validation script.

### Option 3: Extract from PDF (Manual Process)

For enumerations not in field descriptions:
1. Find the enumeration in the PDF manual
2. Add to `enumerations.json` manually
3. Validate: `uv run python validation/scripts/validate_enumerations.py newEnum`

## Enumeration Schema Format

```json
{
  "enumName": {
    "type": "U1",
    "values": [
      {
        "value": 0,
        "name": "snake_case_name",
        "description": "Human readable description"
      }
    ],
    "occurrences": 2,
    "messages": ["UBX-MSG-A", "UBX-MSG-B"]
  }
}
```

### Naming Conventions

- Value names use `snake_case`
- Leading numbers get underscore prefix: `2d_fix` → `_2d_fix`
- Common abbreviations preserved: `dr` (dead reckoning), `gnss`

## Cost Estimates

- Validation per enumeration: ~$0.01-0.02
- Full validation (all 23 enums): ~$0.30-0.50

## Troubleshooting

### "Enumeration not found in ENUM_MESSAGE_MAP"

Add the mapping to `validation/scripts/validate_enumerations.py`:

```python
ENUM_MESSAGE_MAP = {
    # ... existing mappings
    "newEnum": ["UBX-MSG-NAME"],
}
```

### Extraction misses patterns

The regex patterns in `extract_enumerations.py` may not match all formats. Check:
- `parse_enum_values()` function for supported patterns
- Consider adding new patterns for edge cases

### Discrepancies in validation

Common causes:
- Protocol version differences (older manuals have different values)
- Typos in PDF OCR
- Deprecated values removed in newer versions

Review the validation report and update canonical values if needed.

## Integration with Other Workflows

Enumerations are typically stable and don't need extraction when adding new manuals. However:

1. **New message with new enumeration**: Extract → Validate → Add to schema
2. **Existing enumeration with new values**: Validate against new manual → Update schema

The `add_manual.py` orchestrator does not currently handle enumerations automatically. Run validation manually after adding new manuals.
