# UBX Protocol Schema Coverage Report

Generated: 2026-01-10 22:23:26

## Summary

| Component | Count | Status |
|-----------|-------|--------|
| Messages | 239 | Complete |
| Fields | 2032 | Complete |
| Bitfield definitions | 168/176 (95%) | 8 missing |
| Bitfield bits defined | 806 | - |
| Enumerations | 23 | 107 values |
| Config key groups | 47 | Complete |
| Config keys | 1109 | Complete |

## Messages by Class

| Class | Count |
|-------|-------|
| CFG | 47 |
| NAV | 40 |
| MGA | 36 |
| NAV2 | 26 |
| MON | 20 |
| RXM | 19 |
| TIM | 12 |
| LOG | 12 |
| ESF | 7 |
| INF | 5 |
| AID | 5 |
| SEC | 4 |
| HNR | 3 |
| ACK | 2 |
| UPD | 1 |

## Missing Bitfield Definitions

Total: 8 X-type fields without bitfield definitions

### GPIO Pin Masks (raw bitmasks, no protocol-defined structure) (4)

- `UBX-MON-HW`.`pinBank` (X4)
- `UBX-MON-HW`.`pinDir` (X4)
- `UBX-MON-HW`.`pinVal` (X4)
- `UBX-MON-HW`.`usedMask` (X4)

### Legacy Messages (deprecated, not in current manuals) (1)

- `UBX-AID-HUI`.`health` (X4)

### Reserved Fields (2)

- `UBX-CFG-SBAS`.`reserved4_2_7` (X1)
- `UBX-CFG-SBAS`.`reserved5_3_7` (X1)

### Other (1)

- `UBX-LOG-BATCH`.`flags2` (X1)

## Config Keys by Type

| Type | Count |
|------|-------|
| U1 | 721 |
| L | 180 |
| E1 | 41 |
| X8 | 40 |
| U2 | 36 |
| U4 | 31 |
| I4 | 17 |
| I2 | 12 |
| X1 | 10 |
| I1 | 7 |
| R4 | 7 |
| R8 | 6 |
| X2 | 1 |

## Validation Status

To validate the schema, run:

```bash
# Run round-trip tests
cd testing && uv run pytest tests/test_round_trip.py -v

# Cross-validate against pyubx2
uv run python validation/scripts/cross_validate.py --summary

# Regenerate this report
uv run python scripts/generate_coverage_report.py
```

## Data Sources

- **Messages**: Extracted from u-blox PDF interface descriptions
- **Bitfields**: Extracted from PDF manuals via LLM
- **Enumerations**: Extracted from PDF manuals
- **Config Keys**: Extracted from PDF manuals

Cross-validated against:
- [pyubx2](https://github.com/semuconsulting/pyubx2) - Python UBX library
- [ublox-rs](https://github.com/ublox-rs/ublox) - Rust UBX library