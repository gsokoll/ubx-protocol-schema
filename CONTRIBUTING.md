# Contributing to UBX Protocol Schema

Thank you for your interest in contributing! This project provides accurate, machine-readable UBX protocol definitions for u-blox GNSS receivers.

## Quick Links

- [Validated Data](data/ubx/validated/) — Ready-to-use message definitions
- [Schema Design](docs/schema-design-notes.md) — Design rationale and data format
- [Extraction Guide](docs/extraction-guide.md) — How to add new manuals
- [Majority Voting Pipeline](docs/majority-voting-pipeline.md) — Validation process

## How to Contribute

### 1. Reporting Extraction Errors

If you find incorrect field definitions, missing bitfields, or wrong data types:

1. **Open an issue** with:
   - Message name (e.g., `UBX-NAV-PVT`)
   - Field name and the error (e.g., `flags` bitfield missing bit 5)
   - Expected vs actual values
   - Reference to PDF page number if possible

2. **Or fix it directly** — see "Improving Extractions" below.

### 2. Adding New Manuals

When u-blox releases new firmware with updated interface descriptions:

```bash
# 1. Add the manual URL to interface_manuals/manuals.json
{
  "device-family": {
    "manuals": [{
      "title": "u-blox-XX-YYY-Z.ZZ_InterfaceDescription",
      "url": "https://content.u-blox.com/...",
      "local_path": "interface_manuals/device-family/filename.pdf"
    }]
  }
}

# 2. Download the PDF
uv run python scripts/download_manuals.py

# 3. Extract messages (requires Anthropic API key)
export ANTHROPIC_API_KEY=your_key
uv run python scripts/extract_with_anthropic.py \
  --pdf interface_manuals/your-manual.pdf \
  --all-messages

# 4. Run validation
uv run python scripts/validate_majority.py \
  --extractions-dir data/ubx/by-manual \
  --verbose

# 5. Re-extract any outliers identified by validation
uv run python scripts/reextract_outliers.py

# 6. Submit a PR with the new extraction and updated validated files
```

### 3. Improving Extractions

When validation identifies extraction errors (outliers that differ from consensus):

```bash
# Re-extract specific outliers with consensus context
uv run python scripts/reextract_outliers.py

# For messages with version variants (e.g., MON-GNSS, NAV-RELPOSNED)
uv run python scripts/reextract_version_messages.py
```

### 4. Improving the Extraction Prompt

The extraction quality depends on prompts in `src/extraction/prompts.py`. To improve:

1. Identify systematic extraction errors using validation reports
2. Add or update prompts in `src/extraction/prompts.py`:
   - `SHORT_HINTS` — Brief guidance appended to standard prompt
   - `DEDICATED_PROMPTS` — Complete replacement for challenging messages
3. Re-extract affected messages
4. Validate improvements
5. Submit a PR with before/after comparison

### 5. Handling Protocol Inconsistencies

When messages cannot reach consensus due to legitimate protocol evolution (not extraction errors):

```bash
# Generate adjudication reports
uv run python scripts/generate_adjudication_reports.py

# Review reports in analysis_reports/adjudication/
# Update data/ubx/validated/protocol_notes.json with documented decision

# Generate validated JSON for adjudicated messages
uv run python scripts/generate_adjudicated_messages.py
```

## Development Setup

```bash
# Clone the repository
git clone https://github.com/gsokoll/ubx-protocol-schema.git
cd ubx-protocol-schema

# Install dependencies with uv
uv sync

# Run extraction (requires ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY=your_key
uv run python scripts/extract_with_anthropic.py --help
```

## Directory Structure

```
data/
  validated/              # ⭐ Validated message definitions
    messages/             # One JSON per message-version (209 files)
    protocol_notes.json   # Documented protocol inconsistencies
    manifest.json         # Index of all messages
  enumerations.json       # Canonical enum definitions
  by-manual/              # Raw extractions per manual (34 files)

schema/
  ubx-message-schema-v1.2.json   # JSON Schema for message definitions

src/
  extraction/             # PDF extraction pipeline
    extractor.py          # Core extraction logic
    pdf_utils.py          # PDF processing utilities
    prompts.py            # Modular extraction prompts
  validation/             # Majority voting validation
    fingerprint.py        # Structural fingerprinting
    voting.py             # Consensus voting logic
    report.py             # Discrepancy reporting

scripts/
  extract_with_anthropic.py     # Main extraction script
  validate_majority.py          # Majority voting validation
  reextract_outliers.py         # Re-extract outlier messages
  extract_enumerations.py       # Extract enum definitions
  download_manuals.py           # Download PDFs from URLs
  generate_adjudication_reports.py  # Reports for no-consensus messages
  generate_adjudicated_messages.py  # Apply adjudication decisions

docs/                     # Technical documentation
analysis_reports/         # Validation reports and adjudication
interface_manuals/        # PDF download configuration
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
