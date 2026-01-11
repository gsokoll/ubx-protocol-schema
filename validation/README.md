# Validation Framework

Validate and fix UBX message definitions against source PDF manuals. Cross-validate against external libraries for quality assurance.

## Philosophy

**PDF manuals are the authoritative source.** External libraries are used for comparison, not data extraction.

1. **Start with canonical data** - The existing dataset in `data/`
2. **Validate against manuals** - Ask LLM "does this match the PDF?"
3. **Extract missing data** - Use focused prompts for bitfields, etc.
4. **Cross-validate** - Compare against pyubx2 to find potential issues
5. **Fix discrepancies** - Re-extract with focused prompts when needed

## Quick Reference

```bash
# Check dataset quality
uv run python validation/scripts/cross_validate.py --summary

# Fix missing bitfields for a message
uv run python validation/scripts/validate_message.py UBX-NAV-PVT --extract-missing --apply

# Fix all messages with missing bitfields
uv run python validation/scripts/validate_all_messages.py --fix-bitfields

# Find messages missing from schema
uv run python validation/scripts/gap_analysis.py
```

## Data Sources

| Type | File | Description |
|------|------|-------------|
| Messages | `data/messages/ubx_messages.json` | 239 UBX message definitions |
| Enumerations | `data/messages/enumerations.json` | 23 enumeration definitions |
| Config Keys | `data/config_keys/unified_config_keys.json` | 1,109 configuration keys |

## Scripts

### Message Validation & Fixing

| Script | Purpose |
|--------|---------|
| `validate_message.py` | Validate single message, extract/apply bitfield fixes |
| `validate_all_messages.py` | Batch validation with `--fix-bitfields` option |
| `cross_validate.py` | Compare schema against pyubx2 (no data copying) |

### Inventory & Gap Analysis

| Script | Purpose |
|--------|---------|
| `build_inventory.py` | Build message inventory from PDF table of contents |
| `gap_analysis.py` | Find messages in PDFs missing from schema |
| `extract_missing.py` | Extract missing messages from PDFs |
| `merge_extracted.py` | Merge extracted messages into schema |

### Other Validation

| Script | Purpose |
|--------|---------|
| `validate_enumerations.py` | Validate enum values against PDFs |
| `validate_config_keys.py` | Validate config keys against PDFs |
| `resolve_discrepancy.py` | Interactive/auto resolution of mismatches |

## Common Workflows

### Validate a Message

```bash
# Validate against all PDF manuals
uv run python validation/scripts/validate_message.py UBX-NAV-PVT

# Verbose output
uv run python validation/scripts/validate_message.py UBX-NAV-PVT -v
```

### Extract Missing Bitfields

```bash
# Preview what's missing (dry run)
uv run python validation/scripts/validate_message.py UBX-NAV-PVT --extract-missing

# Extract and apply to schema
uv run python validation/scripts/validate_message.py UBX-NAV-PVT --extract-missing --apply
```

### Batch Fix Missing Bitfields

```bash
# Fix all messages with missing bitfields
uv run python validation/scripts/validate_all_messages.py --fix-bitfields

# Preview without applying
uv run python validation/scripts/validate_all_messages.py --fix-bitfields --dry-run

# Parallel processing
uv run python validation/scripts/validate_all_messages.py --fix-bitfields --workers 3
```

### Cross-Validate Against pyubx2

```bash
# Quick summary
uv run python validation/scripts/cross_validate.py --summary

# Check specific message
uv run python validation/scripts/cross_validate.py UBX-NAV-PVT -v

# Full report (saves to reports/)
uv run python validation/scripts/cross_validate.py --all --save
```

### Gap Analysis

```bash
# Find missing messages
uv run python validation/scripts/gap_analysis.py

# Verbose output
uv run python validation/scripts/gap_analysis.py -v
```

## Output Files

| File | Description |
|------|-------------|
| `inventory/pdf_inventory.json` | Messages found in PDF table of contents |
| `inventory/all_messages.json` | All unique message names across PDFs |
| `reports/gap_analysis.json` | Coverage analysis vs PDF inventory |
| `reports/cross_validation.json` | Comparison with pyubx2 |
| `reports/*_validation.json` | Per-message validation results |

## Environment

Requires `GOOGLE_API_KEY` for Gemini API access:

```bash
export GOOGLE_API_KEY="your-api-key"
```

## Related Documentation

- [Message Extraction Workflow](../docs/message-extraction-workflow.md) - Adding new manuals
- [Bitfield Extraction Workflow](../docs/bitfield-extraction-workflow.md) - Fixing bitfields
- [Enumeration Workflow](../docs/enumeration-extraction-workflow.md) - Validating enums
- [Config Key Workflow](../docs/config-key-extraction-workflow.md) - Config key extraction
