# UBX-MON-* Implementation Notes for ublox-rs

## Summary

| Message | Fields | Payload | Complexity | Notes |
|---------|--------|---------|------------|-------|
| **UBX-MON-RXR** | 1 | 1 byte | **Trivial** | Single flag byte with 1 bitfield |
| **UBX-MON-RXBUF** | 3 | 24 bytes | **Easy** | 3 arrays of buffer stats |
| **UBX-MON-TXBUF** | 7 | 28 bytes | **Easy** | 3 arrays + 4 scalars, 1 bitfield |
| **UBX-MON-MSGPP** | 7 | 120 bytes | **Easy** | 7 arrays (port message counters) |
| **UBX-MON-PATCH** | 2 | Variable | **Medium** | Repeated block (N patches) |
| **UBX-MON-SPAN** | 3 | Variable | **Medium** | Repeated block (N RF blocks), includes 256-element spectrum array |

## Recommended PR Order

1. **MON-RXR** — trivial 1-byte message, good warmup
2. **MON-RXBUF** — simple fixed arrays
3. **MON-TXBUF** — similar to RXBUF with a bitfield
4. **MON-MSGPP** — straightforward but larger payload
5. **MON-PATCH** — variable-length with repeated blocks
6. **MON-SPAN** — most complex: variable-length, repeated blocks, 256-element spectrum array per RF block

---

## Message-Specific Implementation Gotchas

### UBX-MON-RXR (trivial)
- **Bitfield consistency**: Some manuals omit the bitfield breakdown for the `flags` byte. The `awake` bit is at bit 0.

### UBX-MON-RXBUF (easy)
- ✅ No variations found across 12 sources. Straightforward implementation.

### UBX-MON-TXBUF (easy)
- **`errors` bitfield gotcha**: The `limit` field spans bits 0-5 (6 bits for 6 targets), not just bit 5. One M8 manual got this wrong.
- Structure: 3 arrays of 6 elements (pending U2, usage U1, peakUsage U1), then 2 scalars, 1 bitfield byte, 1 reserved.

### UBX-MON-MSGPP (easy)
- ✅ Stable across 12 sources. Fixed 120-byte payload.
- 6 ports × 8 protocol counters (U2) + 6 skipped counters (U4).

### UBX-MON-PATCH (medium) ⚠️
- **Two valid message types**: Poll request (0 bytes) AND output response (variable).
- **Documentation variant**: In F9-LAP-1.30, the patch details are **masked as Reserved** (only `patchInfo` X4 visible, rest is 12 bytes reserved). Other manuals expose `comparatorNumber`, `patchAddress`, `patchData`.
- **Bit terminology varies**: `location` bitfield uses "OTP" vs "eFuse" depending on chip generation.
- **Repeated block**: `4 + nEntries * 16` bytes.

### UBX-MON-SPAN (complex) ⚠️
- **Large repeated blocks**: 272 bytes per RF block (mostly 256-byte spectrum array).
- **Scale factor**: Spectrum values are `U1` but represent dB with **0.25 dB resolution** (scale = 2⁻²). Some manuals omit this detail.
- **Variable block count**: `numRfBlocks` in header determines repetitions (typically 1-2 for most receivers).

---

## General Recommendations

1. **Protocol version gating**: MON-SPAN and detailed MON-PATCH fields are Gen9+ (protocol ≥27). Consider feature flags.

2. **Array indexing**: MON-MSGPP/RXBUF/TXBUF all use 6-element arrays indexed by port number (0-5). Document which ports map to which interfaces.

3. **Test with real hardware**: The M8 → M9 → M10 progression has subtle differences. Our data shows consistency, but edge cases exist.

4. **Poll vs Output**: For MON-PATCH, implement both the zero-length poll and the variable-length response.

---

## Data Source

Analysis based on extractions from 12-15 u-blox interface description manuals spanning M8, M9, M10, F9, F10, and X20 product lines, adjudicated for consistency.
