# u-blox UBX Protocol Schema

Machine-readable database of u-blox UBX binary protocol message definitions, extracted from official interface manuals using LLM-based extraction.

## What is this?

u-blox GNSS receivers use the proprietary UBX binary protocol. The protocol is documented in PDF manuals, but there's no official machine-readable format. This project provides **validated, schema-compliant UBX message definitions** for:

- **Code generation** - Parser/serializer code in any language
- **Validation** - Check implementations against canonical definitions
- **Documentation** - Field names, types, offsets, descriptions

## Output Files

| File | Description |
|------|-------------|
| `data/messages/ubx_messages.json` | **239 message definitions** (schema v1.4) |
| `data/messages/enumerations.json` | **23 enumeration definitions** |
| `data/config_keys/unified_config_keys.json` | **1,109 configuration keys** |
| `data/manual_metadata.json` | **Manual-to-protocol version mapping** |

## Quick Start

```bash
# View a message definition
cat data/messages/ubx_messages.json | python3 -c "
import json,sys
data=json.load(sys.stdin)
msg = next(m for m in data['messages'] if m['name'] == 'UBX-NAV-PVT')
print(json.dumps(msg, indent=2)[:500])"
```

## Assessing Dataset Quality

### Coverage Report

See [COVERAGE.md](COVERAGE.md) for current statistics, or regenerate it:

```bash
uv run python scripts/generate_coverage_report.py
```

**Current status:**

| Component | Count | Status |
|-----------|-------|--------|
| Messages | 239 | Complete |
| Fields | 2,032 | Complete |
| Bitfield definitions | 159/173 | 92% complete |
| Enumerations | 23 | 107 values |
| Config keys | 1,109 | Complete |

### Cross-Validation

Compare schema against the pyubx2 library to identify potential issues:

```bash
# Quick summary of differences
uv run python validation/scripts/cross_validate.py --summary

# Detailed comparison for specific message
uv run python validation/scripts/cross_validate.py UBX-NAV-PVT -v

# Full validation report (saved to validation/reports/)
uv run python validation/scripts/cross_validate.py --all --save
```

### Testing

```bash
# Run all tests (round-trip encode/decode, schema integrity)
uv run pytest testing/tests/ -v

# Cross-validate against pyubx2
uv run pytest testing/tests/test_vs_pyubx2.py -v
```

### Gap Analysis

Find messages in PDF manuals that aren't in the schema:

```bash
uv run python validation/scripts/gap_analysis.py
```

## Workflows

This project uses a **validation-first workflow**: PDF manuals are the authoritative source. External libraries are used for cross-validation, not data extraction.

### Adding a New Manual

When u-blox releases a new interface description PDF:

```bash
# Single command - extracts messages, merges, generates report
uv run python scripts/add_manual.py --pdf-path interface_manuals/new-device/manual.pdf

# Full workflow with config keys and bitfield fixes
uv run python scripts/add_manual.py --pdf-path interface_manuals/new-device/manual.pdf \
    --extract-config-keys --fix-bitfields
```

See [docs/message-extraction-workflow.md](docs/message-extraction-workflow.md) for step-by-step details.

### Fixing Existing Messages

To fix missing bitfields or other issues:

```bash
# Single message - validate and extract missing bitfields
uv run python validation/scripts/validate_message.py UBX-NAV-PVT --extract-missing --apply

# Batch - fix all messages with missing bitfields
uv run python validation/scripts/validate_all_messages.py --fix-bitfields
```

See [docs/bitfield-extraction-workflow.md](docs/bitfield-extraction-workflow.md) for details.

### Config Key Extraction

For F9+ devices using CFG-VAL* messages:

```bash
# Extract config keys from a manual
uv run python scripts/bulk_extraction/extract_config_keys_with_gemini.py --pdf-path <manual.pdf>

# Detect conflicts and merge
uv run python scripts/detect_config_key_conflicts.py
uv run python scripts/merge_config_keys.py
```

See [docs/config-key-extraction-workflow.md](docs/config-key-extraction-workflow.md) for details.

### Validating Enumerations

```bash
# List all enumerations
uv run python validation/scripts/validate_enumerations.py --list

# Validate a specific enumeration against PDFs
uv run python validation/scripts/validate_enumerations.py fixType
```

See [docs/enumeration-extraction-workflow.md](docs/enumeration-extraction-workflow.md) for details.

## Directory Structure

```
COVERAGE.md                   # Auto-generated coverage report
CONTRIBUTING.md               # Contribution guide

data/
  messages/
    ubx_messages.json         # Main output: 239 messages
    enumerations.json         # 23 enum definitions
  config_keys/
    unified_config_keys.json  # 1,109 config keys
    by-manual/                # Per-manual extractions
  manual_metadata.json        # PDF to protocol version mapping
  preliminary/                # Staging area for extracted messages

scripts/
  add_manual.py               # Orchestrator for adding new manuals
  generate_coverage_report.py # Generate COVERAGE.md
  bulk_extraction/            # Bulk extraction scripts (historical)

validation/
  scripts/                    # Validation and extraction tools
    build_inventory.py        # Build message inventory from PDFs
    gap_analysis.py           # Compare inventory vs schema
    extract_missing.py        # Extract missing messages
    merge_extracted.py        # Merge extractions into schema
    validate_message.py       # Validate/fix single message
    validate_all_messages.py  # Batch validation and fixing
    cross_validate.py         # Compare against pyubx2
    validate_enumerations.py  # Validate enums against PDFs
  inventory/                  # PDF message inventory
  reports/                    # Validation reports

testing/                      # Test framework
  lib/                        # Schema-based codec
  tests/                      # pytest tests

schema/                       # JSON Schema definitions (v1.4)
docs/                         # Technical documentation
interface_manuals/            # Source PDF manuals (32 files)
```

## Message Schema (v1.4)

```json
{
  "name": "UBX-NAV-PVT",
  "class_id": "0x01",
  "message_id": "0x07",
  "message_type": "periodic_polled",
  "supported_versions": {
    "protocol_versions": [1800, 2712, 2750, 3201, 3410, 5010],
    "min_protocol_version": 1800,
    "source_manuals": ["u-blox8-M8_ReceiverDescrProtSpec_UBX-13003221", "..."]
  },
  "payload": {
    "length": {"fixed": 92},
    "fields": [
      {"name": "iTOW", "byte_offset": 0, "data_type": "U4", "unit": "ms"},
      {"name": "year", "byte_offset": 4, "data_type": "U2"},
      {"name": "fixType", "byte_offset": 20, "data_type": "U1"}
    ]
  }
}
```

### Protocol Version Format

Protocol versions are stored as **integers** (version x 100) for easy comparison:

| Version | Integer |
|---------|--------|
| 18.00 | 1800 |
| 27.50 | 2750 |
| 33.00 | 3300 |
| 50.10 | 5010 |

### Field Types

| Type | Size | Description |
|------|------|-------------|
| U1, U2, U4, U8 | 1-8 bytes | Unsigned integers (little-endian) |
| I1, I2, I4, I8 | 1-8 bytes | Signed integers |
| R4, R8 | 4, 8 bytes | IEEE 754 floats |
| X1, X2, X4 | 1-4 bytes | Bitfields |
| CH | 1 byte | ASCII character |

## Configuration Keys

For F9+ devices using CFG-VAL* messages:

```json
{
  "name": "CFG-RATE-MEAS",
  "key_id": "0x30210001",
  "group": "CFG-RATE",
  "data_type": "U2",
  "description": "Nominal time between GNSS measurements",
  "unit": "ms"
}
```

## Documentation

| Document | Description |
|----------|-------------|
| [message-extraction-workflow.md](docs/message-extraction-workflow.md) | Adding manuals and fixing messages |
| [bitfield-extraction-workflow.md](docs/bitfield-extraction-workflow.md) | Fixing missing bitfield definitions |
| [enumeration-extraction-workflow.md](docs/enumeration-extraction-workflow.md) | Enumeration validation |
| [config-key-extraction-workflow.md](docs/config-key-extraction-workflow.md) | Config key extraction process |
| [schema-design-notes.md](docs/schema-design-notes.md) | Message schema design decisions |
| [config-keys-notes.md](docs/config-keys-notes.md) | Config key schema design notes |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `GOOGLE_API_KEY` | Gemini API for extraction/validation |
| `ANTHROPIC_API_KEY` | Alternative: Anthropic API |

## License

MIT License - see [LICENSE](LICENSE)

## Acknowledgments

- Protocol definitions from [u-blox](https://www.u-blox.com/) interface manuals
- Cross-validation against [pyubx2](https://github.com/semuconsulting/pyubx2) (validation only, no data copying)
