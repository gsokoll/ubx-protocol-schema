# Contributing to UBX Protocol Schema

Thank you for your interest in contributing! This project provides accurate, machine-readable UBX protocol definitions for u-blox GNSS receivers.

## Quick Links

- [Message Extraction Workflow](docs/message-extraction-workflow.md) - Adding manuals and fixing messages
- [Config Key Extraction Workflow](docs/config-key-extraction-workflow.md) - Config key extraction
- [Bitfield Extraction Workflow](docs/bitfield-extraction-workflow.md) - Fixing missing bitfields
- [Enumeration Extraction Workflow](docs/enumeration-extraction-workflow.md) - Enumeration validation
- [Schema Design Notes](docs/schema-design-notes.md) - Design rationale and data format

## How to Contribute

### 1. Reporting Extraction Errors

If you find incorrect field definitions, missing bitfields, or wrong data types:

1. **Open an issue** with:
   - Message name (e.g., `UBX-NAV-PVT`)
   - Field name and the error (e.g., `flags` bitfield missing bit 5)
   - Expected vs actual values
   - Reference to PDF page number if possible

2. **Or fix it directly** - see "Fixing Existing Messages" below.

### 2. Adding New Manuals

When u-blox releases new firmware with updated interface descriptions:

```bash
# Quick method - orchestrator script (messages only)
uv run python scripts/add_manual.py --pdf-path interface_manuals/new-device/manual.pdf

# Full workflow including config keys and bitfields
uv run python scripts/add_manual.py --pdf-path interface_manuals/new-device/manual.pdf \
    --extract-config-keys --fix-bitfields

# Or step-by-step (see docs/message-extraction-workflow.md for details)
uv run python validation/scripts/build_inventory.py
uv run python validation/scripts/gap_analysis.py
uv run python validation/scripts/extract_missing.py --all
uv run python validation/scripts/merge_extracted.py
```

### 3. Fixing Existing Messages

To fix bitfields, fields, or other issues:

```bash
# Single message - validate and extract missing bitfields
uv run python validation/scripts/validate_message.py UBX-NAV-PVT --extract-missing --apply

# Batch - fix all messages with missing bitfields
uv run python validation/scripts/validate_all_messages.py --fix-bitfields
```

### 4. Validating Enumerations

Enumerations are typically stable, but can be validated after adding new manuals:

```bash
# List all enumerations
uv run python validation/scripts/validate_enumerations.py --list

# Validate a specific enumeration
uv run python validation/scripts/validate_enumerations.py fixType

# See docs/enumeration-extraction-workflow.md for details
```

### 5. Improving the Extraction Prompt

The extraction quality depends on prompts in `src/extraction/prompts.py`. To improve:

1. Identify systematic extraction errors using validation reports
2. Add or update prompts in `src/extraction/prompts.py`
3. Re-extract affected messages using `validate_message.py --extract-missing --apply`
4. Validate improvements
5. Submit a PR with before/after comparison

## Development Setup

```bash
# Clone the repository
git clone https://github.com/gsokoll/ubx-protocol-schema.git
cd ubx-protocol-schema

# Install dependencies with uv
uv sync

# Set API key for extraction
export GOOGLE_API_KEY=your_key  # or ANTHROPIC_API_KEY

# Run tests
uv run pytest testing/tests/ -v
```

## Directory Structure

```
data/
  messages/
    ubx_messages.json      # Canonical message definitions (239 messages)
    enumerations.json      # Enumeration definitions
  config_keys/
    unified_config_keys.json  # Configuration keys (1,109 keys)
  manual_metadata.json     # Manual-to-protocol version mapping
  preliminary/             # Staging area for extracted messages

schema/
  ubx-message-schema-v1.4.json   # JSON Schema for message definitions

src/
  extraction/              # PDF extraction pipeline
    extractor.py           # Core extraction logic
    prompts.py             # Modular extraction prompts
  validation/              # Validation and voting logic
    fingerprint.py         # Structural fingerprinting
    voting.py              # Consensus voting logic

scripts/
  add_manual.py                   # Orchestrator for adding new manuals
  generate_coverage_report.py     # Generate COVERAGE.md
  bulk_extraction/                # Historical bulk extraction scripts

validation/
  scripts/                 # Validation and fix tools
    build_inventory.py     # Build message inventory from PDFs
    gap_analysis.py        # Compare inventory vs schema
    extract_missing.py     # Extract missing messages
    merge_extracted.py     # Merge extractions into schema
    validate_message.py    # Validate single message
    validate_all_messages.py  # Batch validation
    cross_validate.py      # Compare against pyubx2
  inventory/               # PDF message inventory
  reports/                 # Validation reports

testing/                   # Test framework
  lib/                     # Schema-based codec
  tests/                   # pytest tests

docs/                      # Technical documentation
interface_manuals/         # PDF manuals (32 files)
```

## Code Style

- Python 3.10+
- Type hints required for public functions
- Follow existing code patterns
- Keep files under 500 lines (refactor if approaching limit)

## Commit Messages

Follow conventional commits:
- `feat:` New feature or message support
- `fix:` Bug fix or extraction correction
- `docs:` Documentation only
- `refactor:` Code restructuring
- `chore:` Maintenance tasks

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
