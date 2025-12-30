# u-blox UBX Protocol Schema

A machine-readable database of u-blox UBX binary protocol message definitions, extracted from official interface description manuals.

## What is this?

u-blox GNSS receivers communicate using the proprietary UBX binary protocol. The protocol is documented in PDF manuals, but there's no official machine-readable format—making it tedious to develop parsers without carefully reading hundreds of pages. This can be slow and error-prone. It's also difficult to understand which messages are supported by which device, or when format changes were introduced.

This project provides **validated, machine-readable UBX message definitions** that can be used for:

- **Code generation** — Generate parser/serializer code in any language
- **Fuzz testing** — Build test strategies from field definitions and enumerations
- **Documentation** — Accurate field names, types, offsets, and descriptions
- **Validation** — Check implementations against canonical definitions

## Coverage

| Metric | Count |
|--------|-------|
| Validated message definitions | 209 |
| Source manuals | 34 |
| Device families | M8, M9, M10, F9, F10, X20 |
| Enumeration definitions | 29 |

**Protocol Versions:** proto14, proto23, proto27, proto31

## Quick Start

Message definitions are in `data/validated/messages/`. Each JSON file describes one message:

```bash
cat data/validated/messages/NAV-PVT-v0.json
```

```json
{
  "name": "UBX-NAV-PVT",
  "class_id": "0x01",
  "message_id": "0x07",
  "description": "Navigation position velocity time solution",
  "consensus": {
    "sources": ["F9-HPG-1.51", "F9-HPG-1.50", "M10-SPG-5.30"],
    "agreement_count": 14,
    "confidence": 0.93
  },
  "fields": [
    { "name": "iTOW", "byte_offset": 0, "data_type": "U4", "unit": "ms" },
    { "name": "year", "byte_offset": 4, "data_type": "U2" },
    { "name": "fixType", "data_type": "U1", "enumeration": { "values": [...] } }
  ]
}
```

## Directory Structure

```
data/
  validated/              # ⭐ Use this! Validated message definitions
    messages/             # One JSON file per message-version (209 files)
    protocol_notes.json   # Known protocol inconsistencies
    manifest.json         # Index of all validated messages
  enumerations.json       # Canonical enum definitions (fixType, dynModel, etc.)
  by-manual/              # Raw extractions per source manual (34 manuals)

schema/                   # JSON Schema definitions for validation
src/                      # Python extraction and validation pipeline
scripts/                  # CLI tools for extraction and maintenance
docs/                     # Technical documentation
analysis_reports/         # Validation reports and adjudication decisions
interface_manuals/        # PDF download configuration
```

## Enumerations

Fields with enumeration values (like `fixType`, `dynModel`, `gnssId`) include structured data:

```json
{
  "name": "fixType",
  "data_type": "U1",
  "enumeration": {
    "name": "fixType",
    "values": [
      {"value": 0, "name": "no_fix", "description": "no fix"},
      {"value": 1, "name": "dr_only", "description": "dead reckoning only"},
      {"value": 2, "name": "fix_2d", "description": "2D-fix"},
      {"value": 3, "name": "fix_3d", "description": "3D-fix"},
      {"value": 4, "name": "gnss_dr", "description": "GNSS + dead reckoning"},
      {"value": 5, "name": "time_only", "description": "time only fix"}
    ]
  }
}
```

Canonical definitions are in `data/enumerations.json` (29 enums across 28 messages).

> **Note:** Enum values may vary by firmware version. The schema captures commonly supported values.

## Code Generation

The schema data is designed to be consumed by code generators. Each message definition includes everything needed to generate:

- **Parser/serializer code** — Field names, types, byte offsets, payload lengths
- **Fuzz test strategies** — Enumeration values for semantically-valid test data
- **Documentation** — Field descriptions, units, scale factors

Example workflow: Read `data/validated/messages/MON-RXBUF-v0.json` and generate a parser struct in your target language.

## Data Format

### Message Structure

```json
{
  "name": "UBX-NAV-PVT",
  "class_id": "0x01",
  "message_id": "0x07",
  "protocol_version": 0,
  "description": "Navigation position velocity time solution",
  "consensus": {
    "sources": ["F9-HPG-1.51", "M10-SPG-5.30"],
    "agreement_count": 14,
    "total_count": 15,
    "confidence": 0.93,
    "payload_length": { "value": 92 }
  },
  "fields": [...]
}
```

### Field Types

| Type | Size | Description |
|------|------|-------------|
| U1, U2, U4 | 1, 2, 4 bytes | Unsigned integers (little-endian) |
| I1, I2, I4 | 1, 2, 4 bytes | Signed integers |
| R4, R8 | 4, 8 bytes | IEEE 754 floats |
| X1, X2, X4 | 1, 2, 4 bytes | Bitfields |
| CH | 1 byte | ASCII character |

### Variant Messages

Some messages have multiple variants:

- **Protocol versions**: `NAV-RELPOSNED-v0` (proto14/23) vs `NAV-RELPOSNED-v1` (proto27+)
- **Direction**: `LOG-FINDTIME-INPUT` vs `LOG-FINDTIME-OUTPUT`
- **Length**: `RXM-RLM-SHORT` vs `RXM-RLM-LONG`

## Protocol Gotchas

During validation, several cases were found where u-blox modified message structures **without incrementing the version field**:

| Message | Change | Affected Firmware |
|---------|--------|-------------------|
| `MGA-INI-TIME-UTC` | `reserved` → `trustedSource` bitfield | F9-HPG-1.50+, M10-SPG-5.10+ |
| `MGA-INI-TIME-GNSS` | `reserved` → `trustedSource` bitfield | Same as above |
| `CFG-NAVX5` v2 | Reserved field layout changed | F9-HPG-1.50+ |
| `SEC-SIG` v1 | `reserved` → `sigSecFlags` bitfield | F10-SPG-6.00 |

Other quirks:
- **Skipped versions**: `CFG-NAVX5` has v0 and v2, but no v1
- **Dual-format messages**: `RXM-PMREQ` has 8-byte and 16-byte formats that coexist

For full details, see `data/validated/protocol_notes.json`.

## Maintaining the Schema

> **Note:** Most users only need the validated data. This section is for maintainers adding new manuals or updating extraction logic.

### Adding a New Manual

```bash
# 1. Add manual URL to interface_manuals/manuals.json
# 2. Download the PDF
uv run python scripts/download_manuals.py

# 3. Extract messages (requires ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY=your_key
uv run python scripts/extract_with_anthropic.py \
  --pdf interface_manuals/your-manual.pdf \
  --all-messages

# 4. Run majority voting validation
uv run python scripts/validate_majority.py \
  --extractions-dir data/by-manual \
  --verbose

# 5. Re-extract any outliers
uv run python scripts/reextract_outliers.py
```

See [docs/extraction-guide.md](docs/extraction-guide.md) for detailed instructions.

### Key Scripts

| Script | Purpose |
|--------|---------|
| `download_manuals.py` | Download PDFs from configured URLs |
| `extract_with_anthropic.py` | Extract messages using Claude API |
| `validate_majority.py` | Run majority voting validation |
| `reextract_outliers.py` | Re-extract messages that differ from consensus |
| `extract_enumerations.py` | Extract and apply enum definitions |
| `generate_adjudication_reports.py` | Generate reports for no-consensus messages |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on:
- Reporting extraction errors
- Adding new manuals
- Improving extraction prompts

## License

MIT License — see [LICENSE](LICENSE)

## Acknowledgments

- Message definitions from [u-blox](https://www.u-blox.com/) interface manuals
- Extraction powered by [Claude AI](https://anthropic.com/)
- PDF archives via [Wayback Machine](https://web.archive.org/)
