# UBX Configuration Key Database Schema - Design Notes

## Version 1.0

---

## Overview

This schema captures u-blox configuration key definitions used with the CFG-VAL* message family (CFG-VALGET, CFG-VALSET, CFG-VALDEL). This key-value configuration system was introduced in the u-blox F9 generation and provides a unified, extensible way to configure receiver behavior.

### Relationship to Message Schema

| Schema | Purpose |
|--------|---------|
| `ubx-message-schema` | Defines UBX message structures (framing, payloads, fields) |
| `ubx-config-keys-schema` | Defines configuration keys used *within* CFG-VAL* message payloads |

The CFG-VAL* messages carry variable-length lists of key-value pairs. This schema defines what those keys mean.

---

## Key ID Structure

Configuration keys are 32-bit identifiers with a defined bit layout:

```
 31  28 27    24 23       16 15                0
┌──────┬────────┬───────────┬──────────────────┐
│ Rsvd │  Size  │  Group ID │     Item ID      │
└──────┴────────┴───────────┴──────────────────┘
   4b      4b        8b            16b
```

### Size Field (bits 27-24)

| Value | Size | Type Examples |
|-------|------|---------------|
| 0x1 | 1 bit | L (bool) |
| 0x2 | 1 byte | U1, I1, X1 |
| 0x3 | 2 bytes | U2, I2, X2 |
| 0x4 | 4 bytes | U4, I4, X4, R4 |
| 0x5 | 8 bytes | U8, I8, R8 |

### Group ID (bits 23-16)

Groups cluster related configuration items. Examples:

| Group ID | Name | Description |
|----------|------|-------------|
| 0x10 | CFG-RATE | Navigation/measurement rate |
| 0x20 | CFG-NAVSPG | Standard precision navigation |
| 0x21 | CFG-NAVHPG | High precision navigation |
| 0x30 | CFG-NMEA | NMEA protocol settings |
| 0x40-0x4F | CFG-UARTn/USB/SPI/I2C | Port configuration |
| 0x50 | CFG-MSGOUT | Message output rates |
| 0x60 | CFG-INFMSG | Information message config |
| 0x70 | CFG-TP | Time pulse configuration |
| 0x80 | CFG-TMODE | Time mode (survey-in, fixed) |

### Item ID (bits 15-0)

Unique identifier within the group for each configuration item.

---

## Storage Layers

Configuration values can exist in multiple storage layers:

| Layer | ID | Persistent | Description |
|-------|----|-----------:|-------------|
| RAM | 0 | No | Current active configuration |
| BBR | 1 | Yes* | Battery-backed RAM (survives reset, not power loss without battery) |
| Flash | 2 | Yes | Non-volatile flash storage |
| Default | 7 | N/A | Factory default values (read-only) |

### Layer Behavior

```
┌─────────────────────────────────────────────────────────┐
│                    CFG-VALSET Flow                       │
├─────────────────────────────────────────────────────────┤
│  1. Write to specified layer(s)                         │
│  2. If RAM layer included → takes effect immediately    │
│  3. If BBR/Flash → survives reset/power cycle           │
│  4. On startup: Flash → BBR → RAM (cascade load)        │
└─────────────────────────────────────────────────────────┘
```

---

## Data Types

### Standard Types

| Type | Size ID | Size | Rust | Description |
|------|---------|------|------|-------------|
| L | 0x1 | 1 bit | `bool` | Boolean/logic value |
| U1 | 0x2 | 1 byte | `u8` | Unsigned 8-bit |
| I1 | 0x2 | 1 byte | `i8` | Signed 8-bit |
| X1 | 0x2 | 1 byte | `u8` | Bitfield 8-bit |
| U2 | 0x3 | 2 bytes | `u16` | Unsigned 16-bit |
| I2 | 0x3 | 2 bytes | `i16` | Signed 16-bit |
| X2 | 0x3 | 2 bytes | `u16` | Bitfield 16-bit |
| U4 | 0x4 | 4 bytes | `u32` | Unsigned 32-bit |
| I4 | 0x4 | 4 bytes | `i32` | Signed 32-bit |
| X4 | 0x4 | 4 bytes | `u32` | Bitfield 32-bit |
| R4 | 0x4 | 4 bytes | `f32` | IEEE 754 float |
| U8 | 0x5 | 8 bytes | `u64` | Unsigned 64-bit |
| I8 | 0x5 | 8 bytes | `i64` | Signed 64-bit |
| R8 | 0x5 | 8 bytes | `f64` | IEEE 754 double |

### String Type

Some keys use variable-length strings (e.g., NMEA talker ID):

```json
{
  "name": "CFG-NMEA-TALKERID",
  "data_type": "string",
  "constraints": {
    "max_length": 2
  }
}
```

---

## Schema Structure

### Groups Definition

```json
{
  "groups": {
    "CFG-RATE": {
      "name": "CFG-RATE",
      "group_id": "0x10",
      "description": "Navigation and measurement rate configuration",
      "category": "Navigation"
    },
    "CFG-UART1": {
      "name": "CFG-UART1",
      "group_id": "0x40",
      "description": "UART1 port configuration",
      "category": "Communication"
    }
  }
}
```

### Key Definition Examples

#### Simple Numeric Key

```json
{
  "name": "CFG-RATE-MEAS",
  "key_id": "0x30210001",
  "group": "CFG-RATE",
  "item_id": "0x0001",
  "data_type": "U2",
  "description": "Nominal time between GNSS measurements",
  "unit": "ms",
  "default_value": 1000,
  "constraints": {
    "min": 25,
    "max": 65535
  },
  "layers": ["RAM", "BBR", "Flash"]
}
```

#### Boolean Key

```json
{
  "name": "CFG-UART1-ENABLED",
  "key_id": "0x10520001",
  "group": "CFG-UART1",
  "item_id": "0x0001",
  "data_type": "L",
  "description": "Enable or disable UART1",
  "default_value": true,
  "layers": ["RAM", "BBR", "Flash"],
  "affects": ["CFG-UART1-BAUDRATE", "CFG-UART1-INPROT", "CFG-UART1-OUTPROT"]
}
```

#### Enumerated Key

```json
{
  "name": "CFG-NAVSPG-DYNMODEL",
  "key_id": "0x20110021",
  "group": "CFG-NAVSPG",
  "item_id": "0x0021",
  "data_type": "U1",
  "description": "Dynamic platform model",
  "default_value": 0,
  "inline_enum": {
    "values": {
      "PORTABLE": { "value": 0, "description": "Portable (default)" },
      "STATIONARY": { "value": 2, "description": "Stationary" },
      "PEDESTRIAN": { "value": 3, "description": "Pedestrian" },
      "AUTOMOTIVE": { "value": 4, "description": "Automotive" },
      "SEA": { "value": 5, "description": "Sea" },
      "AIRBORNE_1G": { "value": 6, "description": "Airborne <1g" },
      "AIRBORNE_2G": { "value": 7, "description": "Airborne <2g" },
      "AIRBORNE_4G": { "value": 8, "description": "Airborne <4g" },
      "WRIST": { "value": 9, "description": "Wrist-worn watch" },
      "BIKE": { "value": 10, "description": "Motorbike" },
      "LAWN_MOWER": { "value": 11, "description": "Robotic lawn mower" },
      "E_SCOOTER": { "value": 12, "description": "E-scooter" }
    }
  },
  "layers": ["RAM", "BBR", "Flash"]
}
```

#### Bitfield Key

```json
{
  "name": "CFG-UART1-INPROT",
  "key_id": "0x20520002",
  "group": "CFG-UART1",
  "item_id": "0x0002",
  "data_type": "X2",
  "description": "Input protocols enabled on UART1",
  "default_value": "0x0007",
  "bitfield": {
    "bits": [
      { "name": "UBX", "bit_start": 0, "bit_end": 0, "data_type": "U", "description": "UBX protocol input", "default": true },
      { "name": "NMEA", "bit_start": 1, "bit_end": 1, "data_type": "U", "description": "NMEA protocol input", "default": true },
      { "name": "RTCM3X", "bit_start": 2, "bit_end": 2, "data_type": "U", "description": "RTCM3 protocol input", "default": true },
      { "name": "SPARTN", "bit_start": 5, "bit_end": 5, "data_type": "U", "description": "SPARTN protocol input", "default": false }
    ]
  },
  "layers": ["RAM", "BBR", "Flash"],
  "dependencies": [
    {
      "key": "CFG-UART1-ENABLED",
      "condition": "CFG-UART1-ENABLED == 1",
      "type": "requires",
      "description": "UART1 must be enabled for input protocols to function"
    }
  ]
}
```

#### Key with Scaled Value

```json
{
  "name": "CFG-NAVSPG-FIXEDALT",
  "key_id": "0x20110013",
  "group": "CFG-NAVSPG",
  "item_id": "0x0013",
  "data_type": "I4",
  "description": "Fixed altitude for 2D fix mode",
  "unit": "m",
  "scale": {
    "raw": "0.01",
    "multiplier": 0.01,
    "representation": {
      "type": "power_of_10",
      "base": 10,
      "exponent": -2
    }
  },
  "default_value": 0,
  "constraints": {
    "min": -214748364,
    "max": 214748364
  },
  "comment": "Stored as cm, displayed as m. Range: approximately ±2147 km",
  "layers": ["RAM", "BBR", "Flash"]
}
```

#### Message Output Rate Key

```json
{
  "name": "CFG-MSGOUT-UBX_NAV_PVT_UART1",
  "key_id": "0x20910007",
  "group": "CFG-MSGOUT",
  "item_id": "0x0007",
  "data_type": "U1",
  "description": "Output rate of UBX-NAV-PVT on UART1",
  "unit": "cycles",
  "default_value": 0,
  "constraints": {
    "min": 0,
    "max": 255
  },
  "comment": "0 = disabled, 1 = every navigation solution, N = every Nth solution",
  "layers": ["RAM", "BBR", "Flash"],
  "dependencies": [
    {
      "key": "CFG-UART1-ENABLED",
      "condition": "CFG-UART1-ENABLED == 1",
      "type": "requires"
    },
    {
      "key": "CFG-UART1-OUTPROT",
      "condition": "(CFG-UART1-OUTPROT & 0x01) != 0",
      "type": "requires",
      "description": "UBX output protocol must be enabled"
    }
  ]
}
```

---

## Key Dependencies

Dependencies capture relationships between configuration keys:

### Dependency Types

| Type | Description |
|------|-------------|
| `requires` | This key only functions when dependency condition is met |
| `conflicts` | This key cannot be used when dependency condition is met |
| `enables` | Setting this key enables the dependent key's functionality |
| `modifies` | This key's behavior changes based on the dependency |

### Example: Port Protocol Dependencies

```
CFG-UART1-ENABLED
    └── enables ──► CFG-UART1-BAUDRATE
    └── enables ──► CFG-UART1-INPROT
    └── enables ──► CFG-UART1-OUTPROT
                        └── requires (UBX bit) ──► CFG-MSGOUT-UBX_*_UART1
                        └── requires (NMEA bit) ──► CFG-MSGOUT-NMEA_*_UART1
```

---

## Rust Code Generation

### Key Constant Generation

```rust
// Generated from schema
pub mod cfg_keys {
    pub mod rate {
        /// Nominal time between GNSS measurements (ms)
        /// Default: 1000, Range: 25-65535
        pub const MEAS: u32 = 0x30210001;
        
        /// Ratio of measurements to navigation solutions  
        /// Default: 1, Range: 1-127
        pub const NAV: u32 = 0x30210002;
    }
    
    pub mod uart1 {
        /// Enable or disable UART1
        pub const ENABLED: u32 = 0x10520001;
        
        /// UART1 baud rate
        pub const BAUDRATE: u32 = 0x40520001;
        
        /// Input protocols enabled on UART1
        pub const INPROT: u32 = 0x20520002;
    }
}
```

### Typed Configuration API

```rust
/// Configuration key with associated value type
pub trait ConfigKey {
    type Value;
    const KEY_ID: u32;
    const NAME: &'static str;
    const LAYERS: &'static [Layer];
}

/// CFG-RATE-MEAS key definition
pub struct CfgRateMeas;

impl ConfigKey for CfgRateMeas {
    type Value = u16;
    const KEY_ID: u32 = 0x30210001;
    const NAME: &'static str = "CFG-RATE-MEAS";
    const LAYERS: &'static [Layer] = &[Layer::Ram, Layer::Bbr, Layer::Flash];
}

impl CfgRateMeas {
    pub const MIN: u16 = 25;
    pub const MAX: u16 = 65535;
    pub const DEFAULT: u16 = 1000;
    pub const UNIT: &'static str = "ms";
}

/// Type-safe configuration builder
pub struct ConfigTransaction {
    keys: Vec<(u32, Vec<u8>)>,
    layers: u8,
}

impl ConfigTransaction {
    pub fn set<K: ConfigKey>(&mut self, value: K::Value) -> &mut Self 
    where K::Value: ToBytes
    {
        self.keys.push((K::KEY_ID, value.to_le_bytes().to_vec()));
        self
    }
    
    pub fn build(&self) -> UbxCfgValset {
        // Build CFG-VALSET message
    }
}

// Usage
let mut txn = ConfigTransaction::new()
    .layer(Layer::Ram | Layer::Bbr);
    
txn.set::<CfgRateMeas>(250)          // Type-safe: expects u16
   .set::<CfgUart1Enabled>(true)      // Type-safe: expects bool
   .set::<CfgNavspgDynmodel>(DynModel::Automotive);  // Type-safe: expects enum

let msg = txn.build();
```

### Enumeration Generation

```rust
/// Dynamic platform model (CFG-NAVSPG-DYNMODEL)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum DynModel {
    Portable = 0,
    Stationary = 2,
    Pedestrian = 3,
    Automotive = 4,
    Sea = 5,
    Airborne1g = 6,
    Airborne2g = 7,
    Airborne4g = 8,
    Wrist = 9,
    Bike = 10,
    LawnMower = 11,
    EScooter = 12,
}

impl From<DynModel> for u8 {
    fn from(val: DynModel) -> u8 {
        val as u8
    }
}

impl TryFrom<u8> for DynModel {
    type Error = InvalidDynModel;
    
    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Portable),
            2 => Ok(Self::Stationary),
            // ...
            _ => Err(InvalidDynModel(value)),
        }
    }
}
```

### Bitfield Generation

```rust
/// UART input protocol mask (CFG-UART1-INPROT)
#[derive(Debug, Clone, Copy, Default)]
pub struct UartInProt(u16);

impl UartInProt {
    pub const UBX: u16 = 1 << 0;
    pub const NMEA: u16 = 1 << 1;
    pub const RTCM3X: u16 = 1 << 2;
    pub const SPARTN: u16 = 1 << 5;
    
    pub fn ubx(&self) -> bool { (self.0 & Self::UBX) != 0 }
    pub fn set_ubx(&mut self, val: bool) { 
        if val { self.0 |= Self::UBX } else { self.0 &= !Self::UBX }
    }
    
    pub fn nmea(&self) -> bool { (self.0 & Self::NMEA) != 0 }
    pub fn set_nmea(&mut self, val: bool) { 
        if val { self.0 |= Self::NMEA } else { self.0 &= !Self::NMEA }
    }
    
    // ... etc
}

impl From<UartInProt> for u16 {
    fn from(val: UartInProt) -> u16 { val.0 }
}
```

---

## CFG-VAL* Message Integration

### CFG-VALSET (Set Configuration)

```rust
pub struct CfgValset {
    pub version: u8,        // Message version (0x00 or 0x01)
    pub layers: LayerMask,  // Target layers
    pub transaction: Option<TransactionInfo>,  // v1 only
    pub cfg_data: Vec<KeyValue>,
}

pub struct KeyValue {
    pub key_id: u32,
    pub value: ConfigValue,
}

pub enum ConfigValue {
    Bool(bool),
    U8(u8),
    I8(i8),
    U16(u16),
    I16(i16),
    U32(u32),
    I32(i32),
    U64(u64),
    I64(i64),
    F32(f32),
    F64(f64),
}
```

### CFG-VALGET (Get Configuration)

```rust
pub struct CfgValgetPoll {
    pub version: u8,
    pub layer: Layer,       // Which layer to read from
    pub keys: Vec<u32>,     // Keys to retrieve
}

pub struct CfgValgetResponse {
    pub version: u8,
    pub layer: Layer,
    pub cfg_data: Vec<KeyValue>,
}
```

### CFG-VALDEL (Delete Configuration)

```rust
pub struct CfgValdel {
    pub version: u8,
    pub layers: LayerMask,  // Layers to delete from (not RAM)
    pub keys: Vec<u32>,
}
```

---

## Validation

The schema supports key validation at multiple levels:

### 1. Type Validation
Ensure value matches declared `data_type`.

### 2. Range Validation
Check against `constraints.min` and `constraints.max`.

### 3. Enumeration Validation
If `enumeration` or `inline_enum` is defined, value must be in set.

### 4. Dependency Validation
Warn if dependencies are not satisfied.

```rust
pub struct ValidationResult {
    pub errors: Vec<ValidationError>,
    pub warnings: Vec<ValidationWarning>,
}

pub enum ValidationError {
    TypeMismatch { key: String, expected: String, got: String },
    OutOfRange { key: String, value: f64, min: f64, max: f64 },
    InvalidEnumValue { key: String, value: u64, valid: Vec<u64> },
    UnsupportedLayer { key: String, layer: Layer },
    ReadOnlyKey { key: String },
}

pub enum ValidationWarning {
    DependencyNotSatisfied { key: String, dependency: String, condition: String },
    DeprecatedKey { key: String, replacement: Option<String> },
    RequiresReset { key: String },
}
```

---

## Key Naming Conventions

u-blox uses consistent naming patterns:

```
CFG-{GROUP}-{ITEM}
CFG-{GROUP}-{SUBGROUP}_{ITEM}

Examples:
  CFG-RATE-MEAS              → Rate group, measurement item
  CFG-UART1-BAUDRATE         → UART1 group, baud rate item
  CFG-MSGOUT-UBX_NAV_PVT_UART1 → Message output, UBX-NAV-PVT on UART1
  CFG-NAVSPG-DYNMODEL        → Nav standard precision, dynamic model
```

---

## Future Considerations

1. **Cross-Reference with Message Schema**: Link `CFG-MSGOUT-*` keys to message definitions in the message schema.

2. **Configuration Profiles**: Support for named configuration profiles (sets of key-value pairs).

3. **Migration Support**: Tools to migrate configurations between device generations when keys change.

4. **Hardware Variants**: Some keys are only available on certain hardware (e.g., `CFG-HW-*` for antenna control).

5. **Security Keys**: Some F9 devices have security-related keys with special access requirements.
