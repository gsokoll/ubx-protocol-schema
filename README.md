# u-blox UBX Protocol Schema

Machine-readable database of u-blox UBX binary protocol message definitions, extracted from official interface manuals using LLM-based extraction.

## What is this?

u-blox GNSS receivers use the proprietary UBX binary protocol. The protocol is documented in PDF manuals, but there's no official machine-readable format. This project provides **validated, schema-compliant UBX message definitions** for:

- **Code generation** — Parser/serializer code in any language
- **Validation** — Check implementations against canonical definitions
- **Documentation** — Field names, types, offsets, descriptions

## Output Files

| File | Description |
|------|-------------|
| `data/messages/ubx_messages.json` | **208 message definitions** (schema v1.3) |
| `data/messages/enumerations.json` | **24 enumeration definitions** |
| `data/config_keys/unified_config_keys.json` | **1,063 configuration keys** |

## Quick Start

```bash
# View a message definition
cat data/messages/ubx_messages.json | python3 -c "
import json,sys
data=json.load(sys.stdin)
msg = next(m for m in data['messages'] if m['name'] == 'UBX-NAV-PVT')
print(json.dumps(msg, indent=2)[:500])"
```

## Validation Results

The schema has been cross-validated against two independent UBX libraries:

| Test | Pass Rate |
|------|-----------|
| Round-trip (our generator → our parser) | 208/208 (100%) |
| Cross-validation vs pyubx2 (Python) | 190/190 (100%) |
| Cross-validation vs ublox-rs (Rust) | 92/92 (100%) |

Run validation:
```bash
cd testing && uv run python3 generate_coverage_report.py
```

## Directory Structure

```
data/
  messages/
    ubx_messages.json       # ⭐ Main output: 208 messages
    enumerations.json       # 24 enum definitions
  config_keys/
    unified_config_keys.json  # 1,063 config keys

_working/                   # Extraction pipeline artifacts
  stage1_extractions/       # Per-manual LLM extractions
  stage2_voting/            # Consensus voting results  
  stage3_adjudication/      # Final adjudicated structures

testing/                    # Validation framework
  lib/                      # Generator, parser, schema loader
  external/                 # pyubx2 and ublox-rs adapters

scripts/                    # Extraction and generation tools
schema/                     # JSON Schema definitions (v1.3)
docs/                       # Technical documentation
```

## Message Schema (v1.3)

```json
{
  "name": "UBX-NAV-PVT",
  "class_id": "0x01",
  "message_id": "0x07",
  "message_type": "periodic_polled",
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

### Field Types

| Type | Size | Description |
|------|------|-------------|
| U1, U2, U4, U8 | 1-8 bytes | Unsigned integers (little-endian) |
| I1, I2, I4, I8 | 1-8 bytes | Signed integers |
| R4, R8 | 4, 8 bytes | IEEE 754 floats |
| X1, X2, X4 | 1-4 bytes | Bitfields |
| CH | 1 byte | ASCII character |

## Extraction Workflow

The extraction uses Gemini models with multi-shot conversations:

```bash
export GOOGLE_API_KEY=your_key

# Stage 1: Extract from PDFs (3 extractions per message)
uv run python scripts/extract_messages_v2.py extract --all-messages

# Stage 2: Consensus voting
uv run python scripts/vote_preliminary_v2.py

# Stage 3: LLM adjudication for conflicts
uv run python scripts/extract_messages_v2.py adjudicate --model 3-flash

# Stage 4: Generate final schema-validated output
uv run python scripts/generate_message_collection.py

# Stage 5: Extract enumerations from field descriptions
uv run python scripts/extract_enumerations.py --output data/messages/enumerations.json
```

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

See [docs/config-key-extraction-workflow.md](docs/config-key-extraction-workflow.md) for details.

## Documentation

| Document | Description |
|----------|-------------|
| [config-key-extraction-workflow.md](docs/config-key-extraction-workflow.md) | Config key extraction process |
| [config-keys-notes.md](docs/config-keys-notes.md) | Config key schema design notes |
| [schema-design-notes.md](docs/schema-design-notes.md) | Message schema design decisions |

## License

MIT License — see [LICENSE](LICENSE)

## Acknowledgments

- Protocol definitions from [u-blox](https://www.u-blox.com/) interface manuals
- Cross-validation against [pyubx2](https://github.com/semuconsulting/pyubx2) and [ublox-rs](https://github.com/ublox-rs/ublox)
