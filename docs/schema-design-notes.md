# UBX Message JSON Schema - Design Notes

## Version 1.5

**Changes from v1.4:**
- Added `variant_aliases` property for backward-compatible lookup of suffix-named variants
- Consolidated multi-variant messages (e.g., UBX-MGA-GPS family) into single messages with `variants` array
- Added `scripts/consolidate_variants.py` for converting suffix-named messages to proper variants
- Added `since_protocol_version` (integer, protocol version × 100) to fields and bitfield bits
- Added `prior_name` to track what a field/bit was called before it was defined (e.g., "reserved4")
- Added `opaque` property for X-type fields that intentionally lack bitfield definitions (hardware-specific or undocumented)

## Version 1.4

**Changes from v1.3:**
- Added `supported_versions.protocol_versions` as integer array (version × 100)
- Added `supported_versions.min_protocol_version` as integer
- Added `supported_versions.source_manuals` for traceability
- Protocol versions range from 1800 (M8) to 5010 (X20)

**Changes from v1.2 (in v1.3):**
- Added machine-readable `base_offset` format for repeated groups

**Changes from v1.1 (in v1.2):**
- Added `version_specific` field overrides for protocol version differences

**Changes from v1.0 (in v1.1):**
- Added support for u-blox 8/M8 device family
- New data types: `I8`, `RU1_3`, `RU2_5`
- New message type: `get_set`
- Added `conditional_interpretation` for union-style fields
- Added `version_support` and `deprecated` metadata
- Added `optional_blocks` for trailing optional data
- Added `alternatives` payload length for multi-length messages

---

## Overview

This schema captures UBX protocol message definitions in a machine-readable format suitable for code generation and documentation. The primary target is Rust driver development, but the schema is language-agnostic.

### Supported Device Families

- u-blox 8 / u-blox M8 (Protocol versions 15.x - 23.x)
- u-blox F9 (Protocol versions 27.x+)
- Future generations following the same UBX frame structure

---

## Key Design Decisions

### 1. Multi-Variant Messages

Some UBX messages have multiple payload formats sharing the same Class/Message ID. Examples:

| Message | Variants | Discriminator |
|---------|----------|---------------|
| `UBX-CFG-VALSET` | v0 simple, v1 with transaction | `version` field at byte 0 |
| `UBX-AID-ALM` | Poll (0 bytes), Poll SV (1 byte), Data (8 or 40 bytes) | Payload length |
| `UBX-MGA-GPS` | EPH, ALM, HEALTH, UTC, IONO | `type` field at byte 0 |
| `UBX-MGA-INI` | POS-XYZ, POS-LLH, TIME-UTC, TIME-GNSS, CLKD, FREQ, EOP | `type` field at byte 0 |
| `UBX-TIM-VCOCAL` | STOP (type=0), SET (type=2), GET (type=3) | `type` field at byte 0 |
| `UBX-CFG-PRT` | UART, USB, SPI, I2C | `portId` field |

> **Extraction Note**: Type-discriminated messages must be listed in `MULTI_VARIANT_MESSAGES` in `scripts/bulk_extraction/extract_messages_v2.py` to ensure all variants are extracted separately.

**Solution**: The `variants` array with `discriminator` objects, plus `variant_aliases` for backward compatibility:

```json
{
  "name": "UBX-MGA-GPS",
  "class_id": "0x13",
  "message_id": "0x00",
  "variant_aliases": ["UBX-MGA-GPS-EPH", "UBX-MGA-GPS-ALM", "UBX-MGA-GPS-HEALTH", "UBX-MGA-GPS-UTC", "UBX-MGA-GPS-IONO"],
  "variants": [
    {
      "name": "EPH",
      "discriminator": {"field": "type", "byte_offset": 0, "value": 1},
      "payload": { "length": {"fixed": 68}, "fields": [...] }
    },
    {
      "name": "ALM",
      "discriminator": {"field": "type", "byte_offset": 0, "value": 2},
      "payload": { "length": {"fixed": 36}, "fields": [...] }
    }
  ]
}
```

The `variant_aliases` property enables tools to look up messages by their legacy suffix names (e.g., `get_message_by_name("UBX-MGA-GPS-EPH")` returns the parent `UBX-MGA-GPS` message). Use `get_variant_by_alias()` to get both the parent message and the specific variant.

**Consolidation Script**: Use `scripts/consolidate_variants.py` to convert suffix-named messages to the proper variants format:

```bash
# Preview changes
uv run python scripts/consolidate_variants.py --family MGA-GPS --dry-run

# Apply changes
uv run python scripts/consolidate_variants.py --family MGA-GPS
```

**Alternative: Length-discriminated variants**:

```json
{
  "name": "UBX-AID-ALM",
  "class_id": "0x0B",
  "message_id": "0x30",
  "message_type": "input_output",
  "variants": [
    {
      "name": "poll_all",
      "description": "Poll almanac for all SVs",
      "discriminator": { "payload_length": 0 },
      "payload": {
        "length": { "fixed": 0 },
        "fields": []
      }
    },
    {
      "name": "poll_sv",
      "description": "Poll almanac for specific SV",
      "discriminator": { "payload_length": 1 },
      "payload": {
        "length": { "fixed": 1 },
        "fields": [
          { "name": "svid", "byte_offset": 0, "data_type": "U1" }
        ]
      }
    },
    {
      "name": "data",
      "description": "Almanac data (with or without optional words)",
      "discriminator": { "payload_length_range": { "min": 8, "max": 40 } },
      "payload": {
        "length": { "alternatives": [8, 40] },
        "fields": [
          { "name": "svid", "byte_offset": 0, "data_type": "U4" },
          { "name": "week", "byte_offset": 4, "data_type": "U4" }
        ],
        "optional_blocks": [
          {
            "name": "almanac_words",
            "base_offset": 8,
            "size_bytes": 32,
            "presence_condition": "week != 0",
            "fields": [
              { "name": "dwrd", "byte_offset": 0, "data_type": { "array_of": "U4", "count": 8 } }
            ]
          }
        ]
      }
    }
  ]
}
```

**Rust mapping**: Generate an enum with struct variants:
```rust
pub enum UbxAidAlm {
    PollAll,
    PollSv { svid: u8 },
    Data(UbxAidAlmData),
}

pub struct UbxAidAlmData {
    pub svid: u32,
    pub week: u32,
    pub dwrd: Option<[u32; 8]>,  // Present only if week != 0
}
```

### 2. Scale Factors

UBX uses various scale representations:

| Documentation | Type | Example Fields |
|---------------|------|----------------|
| `2^-31`, `2^-8`, `2^4` | Power of 2 | Lat/lon, heading |
| `1e-7`, `1e-2`, `1e-3` | Power of 10 | Degrees, percentages |
| Direct multipliers | Fraction/Integer | Various |

**Solution**: Triple representation for flexibility:

```json
{
  "scale": {
    "raw": "2^-8",
    "multiplier": 0.00390625,
    "representation": {
      "type": "power_of_2",
      "base": 2,
      "exponent": -8
    }
  }
}
```

**Rust usage**:
- `raw`: Documentation comments
- `multiplier`: Runtime conversion (`raw_value as f64 * multiplier`)
- `representation`: Compile-time constants or efficient bit shifts

```rust
impl UbxCfgDosc {
    /// Oscillator stability (scale: 2^-8 ppb)
    pub fn with_temp_ppb(&self) -> f64 {
        // Can use bit shift: (self.with_temp as f64) / 256.0
        self.with_temp as f64 * 0.00390625
    }
}
```

### 3. Bitfields

UBX X-type fields contain packed bits. The M8 documentation shows these as graphical diagrams.

**Example from UBX-CFG-ANT `flags` (X2):**

| Bits | Name | Description |
|------|------|-------------|
| 0 | svcs | Enable antenna supply voltage control |
| 1 | scd | Enable short circuit detection |
| 2 | ocd | Enable open circuit detection |
| 3 | pdwnOnSCD | Power down on short circuit |
| 4 | recovery | Enable automatic recovery |

**Schema representation:**

```json
{
  "name": "flags",
  "byte_offset": 0,
  "data_type": "X2",
  "bitfield": [
    { "name": "svcs", "bit_offset": 0, "bit_width": 1, "description": "Enable antenna supply voltage control" },
    { "name": "scd", "bit_offset": 1, "bit_width": 1, "description": "Enable short circuit detection" },
    { "name": "ocd", "bit_offset": 2, "bit_width": 1, "description": "Enable open circuit detection" },
    { "name": "pdwn_on_scd", "bit_offset": 3, "bit_width": 1, "description": "Power down on short circuit" },
    { "name": "recovery", "bit_offset": 4, "bit_width": 1, "description": "Enable automatic recovery" }
  ]
}
```

**Multi-bit fields** (from UBX-CFG-ANT `pins`):

```json
{
  "name": "pin_switch",
  "bit_offset": 0,
  "bit_width": 5,
  "description": "PIO-pin used for switching antenna supply"
}
```

**Rust mapping**:
```rust
pub struct CfgAntFlags(u16);

impl CfgAntFlags {
    pub fn svcs(&self) -> bool { (self.0 & 0x01) != 0 }
    pub fn scd(&self) -> bool { (self.0 & 0x02) != 0 }
    pub fn ocd(&self) -> bool { (self.0 & 0x04) != 0 }
    pub fn pdwn_on_scd(&self) -> bool { (self.0 & 0x08) != 0 }
    pub fn recovery(&self) -> bool { (self.0 & 0x10) != 0 }
}

pub struct CfgAntPins(u16);

impl CfgAntPins {
    pub fn pin_switch(&self) -> u8 { (self.0 & 0x1F) as u8 }
    pub fn pin_scd(&self) -> u8 { ((self.0 >> 5) & 0x1F) as u8 }
    pub fn pin_ocd(&self) -> u8 { ((self.0 >> 10) & 0x1F) as u8 }
    pub fn reconfig(&self) -> bool { (self.0 & 0x8000) != 0 }
}
```

### 4. Repeated Groups

UBX has several repetition patterns:

| Type | Description | Example |
|------|-------------|---------|
| `count_field` | Count from earlier field | `UBX-CFG-DOSC` (numOsc), `UBX-NAV-SAT` (numSvs) |
| `constant` | Fixed repetition count | Protocol ID arrays |
| `optional` | 0 or 1 times based on length | Some trailing fields |
| `fill_remaining` | Repeat until payload exhausted | `UBX-CFG-VALGET` response |

**Example: UBX-CFG-DOSC**

```json
{
  "name": "UBX-CFG-DOSC",
  "payload": {
    "length": { "variable": { "base": 4, "formula": "4 + 32*numOsc" } },
    "fields": [
      { "name": "version", "byte_offset": 0, "data_type": "U1" },
      { "name": "num_osc", "byte_offset": 1, "data_type": "U1" },
      { "name": "reserved1", "byte_offset": 2, "data_type": { "array_of": "U1", "count": 2 }, "reserved": true }
    ],
    "repeated_groups": [
      {
        "name": "oscillator",
        "repetition_type": "count_field",
        "count_field": "num_osc",
        "group_size_bytes": 32,
        "base_offset": 4,
        "fields": [
          { "name": "osc_id", "byte_offset": 0, "data_type": "U1" },
          { "name": "reserved2", "byte_offset": 1, "data_type": "U1", "reserved": true },
          { "name": "flags", "byte_offset": 2, "data_type": "X2", "bitfield": { "bits": [...] } },
          { "name": "freq", "byte_offset": 4, "data_type": "U4", "scale": { "raw": "2^-2", "multiplier": 0.25 }, "unit": "Hz" }
        ]
      }
    ]
  }
}
```

**Rust mapping**:
```rust
pub struct UbxCfgDosc {
    pub version: u8,
    pub oscillators: Vec<Oscillator>,  // or heapless::Vec for no_std
}

pub struct Oscillator {
    pub osc_id: OscillatorId,
    pub flags: OscillatorFlags,
    pub freq: u32,        // Raw value
    pub phase_offset: i32,
    // ...
}

impl Oscillator {
    pub fn freq_hz(&self) -> f64 {
        self.freq as f64 * 0.25  // 2^-2 scaling
    }
}
```

### 5. Conditional Interpretation (Union Fields)

Some M8 fields change meaning based on flags. This is common in `UBX-AID-INI`:

| Field | When | Unit | Description |
|-------|------|------|-------------|
| `ecefXOrLat` | `flags.lla == 0` | cm | ECEF X coordinate |
| `ecefXOrLat` | `flags.lla == 1` | deg×10⁻⁷ | Latitude |
| `clkDOrFreq` | `flags.clockD == 1` | ns/s | Clock drift |
| `clkDOrFreq` | `flags.clockF == 1` | Hz×10⁻² | Frequency |

**Schema representation:**

```json
{
  "name": "ecef_x_or_lat",
  "byte_offset": 0,
  "data_type": "I4",
  "conditional_interpretation": {
    "selector_field": "flags",
    "interpretations": [
      {
        "when": "flags.lla == 0",
        "name": "ecef_x",
        "unit": "cm",
        "description": "WGS84 ECEF X coordinate"
      },
      {
        "when": "flags.lla == 1",
        "name": "lat",
        "unit": "deg",
        "scale": { "raw": "1e-7", "multiplier": 1e-7 },
        "description": "WGS84 Latitude"
      }
    ]
  }
}
```

**Rust mapping**:
```rust
pub struct UbxAidIni {
    raw_ecef_x_or_lat: i32,
    raw_ecef_y_or_lon: i32,
    raw_ecef_z_or_alt: i32,
    pub flags: AidIniFlags,
    // ...
}

impl UbxAidIni {
    pub fn position(&self) -> Position {
        if self.flags.lla() {
            Position::Lla {
                lat_deg: self.raw_ecef_x_or_lat as f64 * 1e-7,
                lon_deg: self.raw_ecef_y_or_lon as f64 * 1e-7,
                alt_cm: self.raw_ecef_z_or_alt,
            }
        } else {
            Position::Ecef {
                x_cm: self.raw_ecef_x_or_lat,
                y_cm: self.raw_ecef_y_or_lon,
                z_cm: self.raw_ecef_z_or_alt,
            }
        }
    }
}

pub enum Position {
    Ecef { x_cm: i32, y_cm: i32, z_cm: i32 },
    Lla { lat_deg: f64, lon_deg: f64, alt_cm: i32 },
}
```

### 6. Enumerations

Two patterns supported:

**Shared enumerations** (referenced by multiple messages):

```json
{
  "enumerations": {
    "gnss_id": {
      "description": "GNSS system identifier",
      "underlying_type": "U1",
      "values": {
        "GPS": { "value": 0, "description": "GPS" },
        "SBAS": { "value": 1, "description": "SBAS" },
        "Galileo": { "value": 2, "description": "Galileo" },
        "BeiDou": { "value": 3, "description": "BeiDou" },
        "IMES": { "value": 4, "description": "IMES" },
        "QZSS": { "value": 5, "description": "QZSS" },
        "GLONASS": { "value": 6, "description": "GLONASS" }
      }
    }
  }
}
```

**Inline enumerations** (specific to one field):

```json
{
  "name": "dgnss_mode",
  "byte_offset": 0,
  "data_type": "U1",
  "inline_enum": {
    "values": {
      "RtkFloat": { "value": 2, "description": "RTK float, no ambiguity fixing" },
      "RtkFixed": { "value": 3, "description": "RTK fixed, ambiguities fixed when possible" }
    }
  }
}
```

**Rust mapping**:
```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum GnssId {
    Gps = 0,
    Sbas = 1,
    Galileo = 2,
    BeiDou = 3,
    Imes = 4,
    Qzss = 5,
    Glonass = 6,
}

impl TryFrom<u8> for GnssId {
    type Error = UnknownGnssId;
    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Gps),
            1 => Ok(Self::Sbas),
            // ...
            _ => Err(UnknownGnssId(value)),
        }
    }
}
```

### 7. Version Support and Deprecation

M8 messages specify protocol version support and some are deprecated:

```json
{
  "name": "UBX-AID-ALM",
  "supported_versions": {
    "protocol_versions": ["15", "15.01", "16", "17", "18", "19", "19.1", "19.2", "20", "20.01", "20.1", "20.2", "20.3", "22", "22.01", "23", "23.01"],
    "device_families": ["u-blox 8", "u-blox M8"]
  },
  "deprecated": {
    "is_deprecated": true,
    "replacement": "UBX-MGA messages",
    "note": "All UBX-AID messages are deprecated; use UBX-MGA messages instead"
  }
}
```

**Rust mapping**:
```rust
/// Poll GPS aiding almanac data
/// 
/// # Deprecated
/// All UBX-AID messages are deprecated. Use UBX-MGA messages instead.
/// 
/// # Supported Versions
/// Protocol versions 15.x through 23.x on u-blox 8/M8 devices.
#[deprecated(since = "protocol-15", note = "Use UBX-MGA messages instead")]
pub struct UbxAidAlmPoll;
```

### 8. Protocol Version Changes (Silent Changes)

Some fields and bitfield bits were reserved in earlier protocol versions and became defined later. These changes happen **without** the message's internal version field being bumped (if it even has one).

**Problem**: UBX-CFG-NAV5 byte 30 was reserved in protocol versions < 16.00, then became `utcStandard` starting in protocol 16.00. The message has no internal version field, so this is a "silent change."

**Solution**: Use `since_protocol_version` (integer, protocol version × 100) to track when a field/bit was introduced:

```json
{
  "name": "utcStandard",
  "byte_offset": 30,
  "data_type": "U1",
  "description": "UTC standard to be used",
  "since_protocol_version": 1600,
  "prior_name": "reserved4"
}
```

**For bitfield bits**:

```json
{
  "name": "flags",
  "byte_offset": 8,
  "data_type": "X4",
  "bitfield": {
    "bits": [
      {
        "name": "newFeatureFlag",
        "bit_start": 7,
        "bit_end": 7,
        "data_type": "U",
        "description": "Enable new feature (protocol 27.50+)",
        "since_protocol_version": 2750,
        "prior_name": "reserved"
      }
    ]
  }
}
```

**Properties**:
- `since_protocol_version`: Integer protocol version (×100) when the field/bit was introduced
- `prior_name`: What the field/bit was called before (optional, for documentation)

**Code generation**: Before protocol version threshold, treat the field/bit as reserved (ignore on read, zero on write).

### 9. Opaque Fields (No Bitfield Definitions)

Some X-type fields intentionally lack bitfield definitions because:
- **Hardware-specific**: Bit meanings depend on device variant (e.g., GPIO pin masks)
- **Undocumented**: u-blox PDFs don't document the bit structure
- **Deprecated**: Legacy messages where bitfield extraction isn't worthwhile

**Solution**: Mark these fields with `opaque: true`:

```json
{
  "name": "pinBank",
  "byte_offset": 4,
  "data_type": "X4",
  "opaque": true,
  "description": "Mask of pins set as bank A/B (hardware-specific, no protocol-defined bit structure)"
}
```

**Fields marked as opaque:**

| Message | Field | Reason |
|---------|-------|--------|
| UBX-AID-HUI | health | Deprecated legacy message (M8 era) |
| UBX-LOG-BATCH | flags2 | Explicitly undocumented in PDFs |
| UBX-MON-HW | pinBank, pinDir, pinVal, usedMask | Hardware-specific GPIO masks |

**Code generation**: Treat opaque fields as raw integers (no bit unpacking). The VP array in UBX-MON-HW provides per-pin mappings instead.

---

## UBX Data Type Reference

### Standard Types

| UBX Type | Size | Rust Type | Description |
|----------|------|-----------|-------------|
| U1 | 1 | `u8` | Unsigned byte |
| I1 | 1 | `i8` | Signed byte (2's complement) |
| X1 | 1 | `u8` | Bitfield byte |
| U2 | 2 | `u16` | Unsigned short (little-endian) |
| I2 | 2 | `i16` | Signed short (little-endian) |
| X2 | 2 | `u16` | Bitfield short |
| U4 | 4 | `u32` | Unsigned long (little-endian) |
| I4 | 4 | `i32` | Signed long (little-endian) |
| X4 | 4 | `u32` | Bitfield long |
| R4 | 4 | `f32` | IEEE 754 single precision |
| R8 | 8 | `f64` | IEEE 754 double precision |
| I8 | 8 | `i64` | Signed long long (little-endian) |
| CH | 1 | `u8` | ASCII character |

### Special M8 Types

| UBX Type | Size | Description | Decoding |
|----------|------|-------------|----------|
| RU1_3 | 1 | Binary float (3-bit exponent) | `(value & 0x1F) << (value >> 5)` |
| RU2_5 | 2 | Binary float (5-bit exponent) | `(value & 0x7FF) << (value >> 11)` |

**Rust implementation for RU1_3:**
```rust
/// Decode RU1_3 binary floating point
/// Format: eeeb_bbbb where b=base (5 bits), e=exponent (3 bits)
pub fn decode_ru1_3(value: u8) -> u32 {
    let base = (value & 0x1F) as u32;
    let exp = (value >> 5) as u32;
    base << exp
}
```

---

## Message Class Reference (M8)

| Name | Class ID | Description |
|------|----------|-------------|
| NAV | 0x01 | Navigation results (position, velocity, time) |
| RXM | 0x02 | Receiver manager (satellite status) |
| INF | 0x04 | Information messages |
| ACK | 0x05 | Acknowledge/reject messages |
| CFG | 0x06 | Configuration |
| UPD | 0x09 | Firmware update |
| MON | 0x0A | Monitoring |
| AID | 0x0B | AssistNow aiding *(deprecated)* |
| TIM | 0x0D | Timing |
| ESF | 0x10 | External sensor fusion |
| MGA | 0x13 | Multiple GNSS assistance |
| LOG | 0x21 | Logging |
| SEC | 0x27 | Security features |
| HNR | 0x28 | High-rate navigation |

---

## Parsing Strategy

### Frame Parsing

1. Scan for sync bytes `0xB5 0x62`
2. Read class (1 byte) + message ID (1 byte)
3. Read length (2 bytes, little-endian)
4. Read payload (length bytes)
5. Read checksum (2 bytes: CK_A, CK_B)
6. Verify checksum using 8-bit Fletcher algorithm

### Checksum Verification

```rust
fn verify_checksum(class: u8, msg_id: u8, payload: &[u8], ck_a: u8, ck_b: u8) -> bool {
    let mut a: u8 = 0;
    let mut b: u8 = 0;
    
    a = a.wrapping_add(class);
    b = b.wrapping_add(a);
    a = a.wrapping_add(msg_id);
    b = b.wrapping_add(a);
    
    let len = payload.len() as u16;
    a = a.wrapping_add(len as u8);
    b = b.wrapping_add(a);
    a = a.wrapping_add((len >> 8) as u8);
    b = b.wrapping_add(a);
    
    for &byte in payload {
        a = a.wrapping_add(byte);
        b = b.wrapping_add(a);
    }
    
    a == ck_a && b == ck_b
}
```

### Variant Selection

For messages with variants, selection order:

1. Check `payload_length` exact match
2. Check `payload_length_range`
3. Check discriminator `field` at `byte_offset` for `value` match
4. Fall back to default variant (if defined)

### Variable-Length Calculation

For messages with repeated groups:

```rust
fn expected_length(base: usize, count: usize, group_size: usize) -> usize {
    base + count * group_size
}

// Example: UBX-CFG-DOSC
let expected = expected_length(4, num_osc as usize, 32);
```

---

## Reserved Fields

Fields marked `"reserved": true`:

- **Parsing**: Skip the bytes (don't store)
- **Serializing**: Write zeros
- **API**: Don't expose publicly

```rust
// Internal struct may include reserved for round-trip fidelity
struct UbxCfgDoscInternal {
    version: u8,
    num_osc: u8,
    reserved1: [u8; 2],  // Keep for serialization
    oscillators: Vec<OscillatorInternal>,
}

// Public API hides reserved fields
pub struct UbxCfgDosc {
    pub version: u8,
    pub oscillators: Vec<Oscillator>,
}
```

---

## Validity Flags

Some fields are only valid when a flag is set:

```json
{
  "name": "head_veh",
  "byte_offset": 84,
  "data_type": "I4",
  "scale": { "raw": "1e-5", "multiplier": 1e-5 },
  "unit": "deg",
  "validity_flag": "flags.head_veh_valid"
}
```

**Rust mapping**:
```rust
impl NavPvt {
    pub fn head_veh_deg(&self) -> Option<f64> {
        if self.flags.head_veh_valid() {
            Some(self.head_veh_raw as f64 * 1e-5)
        } else {
            None
        }
    }
}
```

---

## Future Considerations

1. **Configuration Key Database**: CFG-VAL* messages use 32-bit key IDs mapping to typed values. A separate schema for the key database would complement this message schema.

2. **NMEA Sentence Definitions**: Could extend schema concept to cover NMEA output messages.

3. **Cross-Generation Differences**: Consider adding more detailed version constraints as F9/M10 introduce incompatible changes.

4. **Validation Rules**: Add `constraints` for min/max values, valid ranges.

5. **Default Values**: Some fields have defaults when polling. Could add `default` property.
