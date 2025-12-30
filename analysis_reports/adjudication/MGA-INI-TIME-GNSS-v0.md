# Adjudication Report: UBX-MGA-INI-TIME-GNSS v0

**Generated:** 2025-12-30 12:13
**Total sources:** 25
**Unique structures:** 6

---

## Summary

**Majority structure:** 15/25 sources
- Sources: u-blox-20-HPG-2.00_InterfaceDe..., u-blox-F10-SPG-6.00_InterfaceD..., u-blox-F9-DBD-1.30_InterfaceDe..., u-blox-F9-HPG-1.50_InterfaceDe..., u-blox-F9-HPG-1.51_InterfaceDe......

**Minority structures:**
- 6 sources: F9-HPS120_Interfacedescription..., LAP120_Interfacedescription_UB..., M9-MDR-2.10_InterfaceDescripti......
- 1 sources: F9-HPS-1.21_InterfaceDescripti...
- 1 sources: M9-ADR-5.10_InterfaceDescripti...
- 1 sources: M9-ADR-5.15_InterfaceDescripti...
- 1 sources: u-blox8-M8_ReceiverDescrProtSp...

---

## Field Differences

### Offset 3

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **leapSecs** | leapSecs | I1 | F9-HPS-1.21_InterfaceDescripti... | Number of leap seconds since 1980 (or 0x... |
| **gnssId** | gnssId | U1 | F9-HPS120_Interfacedescription..., LAP120_Interfacedescription_UB..., M9-ADR-5.10_InterfaceDescripti... (+21 more) | Source of time information. Currently su... |

### Offset 4

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **year** | year | U2 | F9-HPS-1.21_InterfaceDescripti... | Year |
| **reserved0** | reserved0 | U1[2] | F9-HPS120_Interfacedescription..., LAP120_Interfacedescription_UB..., M9-MDR-2.10_InterfaceDescripti... (+3 more) | Reserved |
| **reserved0** | reserved0 | U1 | M9-ADR-5.10_InterfaceDescripti... | Reserved |
| **bitfield0** | bitfield0 | X1 | M9-ADR-5.15_InterfaceDescripti..., u-blox-20-HPG-2.00_InterfaceDe..., u-blox-F10-SPG-6.00_InterfaceD... (+14 more) | bitfield |

### Offset 5

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **reserved1** | reserved1 | U1 | M9-ADR-5.10_InterfaceDescripti..., M9-ADR-5.15_InterfaceDescripti..., u-blox8-M8_ReceiverDescrProtSp... | Reserved |
| **reserved0** | reserved0 | U1 | u-blox-20-HPG-2.00_InterfaceDe..., u-blox-F10-SPG-6.00_InterfaceD..., u-blox-F9-DBD-1.30_InterfaceDe... (+12 more) | Reserved |

### Offset 6

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **month** | month | U1 | F9-HPS-1.21_InterfaceDescripti... | Month, starting at 1 |
| **week** | week | U2 | F9-HPS120_Interfacedescription..., LAP120_Interfacedescription_UB..., M9-ADR-5.10_InterfaceDescripti... (+21 more) | GNSS week number |

### Offset 8

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **hour** | hour | U1 | F9-HPS-1.21_InterfaceDescripti... | Hour, from 0 to 23 |
| **tow** | tow | U4 | F9-HPS120_Interfacedescription..., LAP120_Interfacedescription_UB..., M9-ADR-5.10_InterfaceDescripti... (+21 more) | GNSS time of week |

### Offset 18

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **reserved1** | reserved1 | U1[2] | F9-HPS-1.21_InterfaceDescripti..., F9-HPS120_Interfacedescription..., LAP120_Interfacedescription_UB... (+21 more) | Reserved |
| **reserved2** | reserved2 | U1[2] | u-blox8-M8_ReceiverDescrProtSp... | Reserved |

---

## Full Structure Comparison

### Structure 1 (15 sources)

**Sources:** u-blox-20-HPG-2.00_InterfaceDe..., u-blox-F10-SPG-6.00_InterfaceD..., u-blox-F9-DBD-1.30_InterfaceDe..., u-blox-F9-HPG-1.50_InterfaceDe..., u-blox-F9-HPG-1.51_InterfaceDe..., u-blox-F9-HPG-L1L5-1.40_Interf..., u-blox-F9-HPS-1.30_InterfaceDe..., u-blox-F9-HPS-1.40_InterfaceDe..., u-blox-F9-LAP-1.30_InterfaceDe..., u-blox-F9-LAP-1.50_InterfaceDe..., u-blox-M10-SPG-5.10_InterfaceD..., u-blox-M10-SPG-5.30_InterfaceD..., u-blox-M9-MDR-2.16_InterfaceDe..., u-blox-M9-SPG-4.04_InterfaceDe..., u-blox-X20-HPG-2.02_InterfaceD...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | type | U1 | Message type (0x11 for this type) |
| 1 | version | U1 | Message version (0x00 for this version) |
| 2 | ref | X1 | Reference to be used to set time |
| 3 | gnssId | U1 | Source of time information. Currently supported: •... |
| 4 | bitfield0 | X1 | bitfield: |
| 5 | reserved0 | U1 | Reserved |
| 6 | week | U2 | GNSS week number |
| 8 | tow | U4 | GNSS time of week |
| 12 | ns | U4 | GNSS time of week, nanosecond part from 0 to 999,9... |
| 16 | tAccS | U2 | Seconds part of time accuracy |
| 18 | reserved1 | U1[2] | Reserved |
| 20 | tAccNs | U4 | Nanoseconds part of time accuracy, from 0 to 999,9... |


### Structure 2 (6 sources)

**Sources:** F9-HPS120_Interfacedescription..., LAP120_Interfacedescription_UB..., M9-MDR-2.10_InterfaceDescripti..., u-blox-F9-HPG-1.13_InterfaceDe..., u-blox-F9-HPG-1.32_InterfaceDe..., u-blox_ZED-F9H_InterfaceDescri...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | type | U1 | Message type (0x11 for this type) |
| 1 | version | U1 | Message version (0x00 for this version) |
| 2 | ref | X1 | Reference to be used to set time |
| 3 | gnssId | U1 | Source of time information. Currently supported: 0... |
| 4 | reserved0 | U1[2] | Reserved |
| 6 | week | U2 | GNSS week number |
| 8 | tow | U4 | GNSS time of week |
| 12 | ns | U4 | GNSS time of week, nanosecond part from 0 to 999,9... |
| 16 | tAccS | U2 | Seconds part of time accuracy |
| 18 | reserved1 | U1[2] | Reserved |
| 20 | tAccNs | U4 | Nanoseconds part of time accuracy, from 0 to 999,9... |


### Structure 3 (1 sources)

**Sources:** F9-HPS-1.21_InterfaceDescripti...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | type | U1 | Message type (0x11 for this type) |
| 1 | version | U1 | Message version (0x00 for this version) |
| 2 | ref | X1 | Reference to be used to set time |
| 3 | leapSecs | I1 | Number of leap seconds since 1980 (or 0x80 = -128 ... |
| 4 | year | U2 | Year |
| 6 | month | U1 | Month, starting at 1 |
| 7 | day | U1 | Day, starting at 1 |
| 8 | hour | U1 | Hour, from 0 to 23 |
| 9 | minute | U1 | Minute, from 0 to 59 |
| 10 | second | U1 | Seconds, from 0 to 59 |
| 11 | reserved0 | U1 | Reserved |
| 12 | ns | U4 | Nanoseconds, from 0 to 999,999,999 |
| 16 | tAccS | U2 | Seconds part of time accuracy |
| 18 | reserved1 | U1[2] | Reserved |
| 20 | tAccNs | U4 | Nanoseconds part of time accuracy, from 0 to 999,9... |


### Structure 4 (1 sources)

**Sources:** M9-ADR-5.10_InterfaceDescripti...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | type | U1 | Message type (0x11 for this type) |
| 1 | version | U1 | Message version (0x00 for this version) |
| 2 | ref | X1 | Reference to be used to set time |
| 3 | gnssId | U1 | Source of time information. Currently supported: 0... |
| 4 | reserved0 | U1 | Reserved |
| 5 | reserved1 | U1 | Reserved |
| 6 | week | U2 | GNSS week number |
| 8 | tow | U4 | GNSS time of week |
| 12 | ns | U4 | GNSS time of week, nanosecond part from 0 to 999,9... |
| 16 | tAccS | U2 | Seconds part of time accuracy |
| 18 | reserved1 | U1[2] | Reserved |
| 20 | tAccNs | U4 | Nanoseconds part of time accuracy, from 0 to 999,9... |


### Structure 5 (1 sources)

**Sources:** M9-ADR-5.15_InterfaceDescripti...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | type | U1 | Message type (0x11 for this type) |
| 1 | version | U1 | Message version (0x00 for this version) |
| 2 | ref | X1 | Reference to be used to set time |
| 3 | gnssId | U1 | Source of time information. Currently supported: 0... |
| 4 | bitfield0 | X1 | bitfield |
| 5 | reserved1 | U1 | Reserved |
| 6 | week | U2 | GNSS week number |
| 8 | tow | U4 | GNSS time of week |
| 12 | ns | U4 | GNSS time of week, nanosecond part from 0 to 999,9... |
| 16 | tAccS | U2 | Seconds part of time accuracy |
| 18 | reserved1 | U1[2] | Reserved |
| 20 | tAccNs | U4 | Nanoseconds part of time accuracy, from 0 to 999,9... |


### Structure 6 (1 sources)

**Sources:** u-blox8-M8_ReceiverDescrProtSp...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | type | U1 | Message type (0x40 for this type) |
| 1 | version | U1 | Message version (0x00 for this version) |
| 2 | ref | X1 | Reference time source |
| 3 | gnssId | U1 | GNSS identifier |
| 4 | bitfield0 | X1 | Configuration flags |
| 5 | reserved1 | U1 | Reserved |
| 6 | week | U2 | Week number |
| 8 | tow | U4 | Time of week |
| 12 | ns | U4 | Nanoseconds |
| 16 | tAccS | U2 | Time accuracy in seconds |
| 18 | reserved2 | U1[2] | Reserved |
| 20 | tAccNs | U4 | Time accuracy in nanoseconds |


---

## Adjudication Decision

- [x] Majority structure is correct
- [ ] Minority structure is correct
- [x] Both are valid (different firmware versions)
- [ ] Extraction error - needs re-extraction

**Decision:** Both structures are valid - same issue as MGA-INI-TIME-UTC.

**Rationale:** 
Same pattern as MGA-INI-TIME-UTC - `trustedSource` bitfield added at offset 11 without version bump.

**Recommendation:** Use majority structure as canonical (represents latest firmware). Already documented in `protocol_notes.json`.

**Canonical source:** X20-HPG-2.02, F9-HPG-1.51, M10-SPG-5.30 (latest firmware versions)
