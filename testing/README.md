# UBX Protocol Schema Testing

This folder contains tests to validate the UBX message schema dataset against external libraries.

## Quick Start

```bash
# Install dependencies
uv pip install pyubx2 pytest

# Run all tests
uv run pytest testing/tests/ -v

# Run specific test categories
uv run pytest testing/tests/test_round_trip.py -v      # Self-consistency
uv run pytest testing/tests/test_vs_pyubx2.py -v       # Cross-validation
```

## Architecture

```
testing/
├── lib/                    # Our UBX codec implementation
│   ├── schema_loader.py    # Load ubx_messages.json
│   ├── ubx_generator.py    # Generate UBX binary from schema
│   └── ubx_parser.py       # Parse UBX binary using schema
│
├── external/               # External library adapters
│   └── pyubx2_adapter.py   # Wrapper for pyubx2
│
├── tests/                  # pytest test suites
│   ├── test_round_trip.py  # Generate→Parse→Compare
│   └── test_vs_pyubx2.py   # Cross-validate with pyubx2
│
└── reports/                # Test output
```

## Test Categories

### 1. Round-Trip Tests
Validates our generator and parser are internally consistent:
```
Our Schema → Generate UBX → Parse with Our Parser → Compare
```

### 2. Cross-Validation vs pyubx2
Confirms our schema matches the widely-used pyubx2 library:
```
Our Schema → Generate UBX → Parse with pyubx2 → Compare
pyubx2 → Generate UBX → Parse with Our Parser → Compare
```

## Coverage

Run the coverage report to see which messages have been tested:
```bash
uv run python testing/generate_coverage_report.py
```
