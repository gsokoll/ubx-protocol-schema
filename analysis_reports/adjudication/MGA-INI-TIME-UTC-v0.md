# Adjudication Report: UBX-MGA-INI-TIME-UTC v0

**Generated:** 2025-12-30 12:13
**Total sources:** 24
**Unique structures:** 2

---

## Summary

**Majority structure:** 16/24 sources
- Sources: M9-ADR-5.15_InterfaceDescripti..., u-blox-20-HPG-2.00_InterfaceDe..., u-blox-F10-SPG-6.00_InterfaceD..., u-blox-F9-DBD-1.30_InterfaceDe..., u-blox-F9-HPG-1.50_InterfaceDe......

**Minority structures:**
- 8 sources: F9-HPS-1.21_InterfaceDescripti..., F9-HPS120_Interfacedescription..., LAP120_Interfacedescription_UB......

---

## Field Differences

### Offset 11

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **reserved0** | reserved0 | U1 | F9-HPS-1.21_InterfaceDescripti..., F9-HPS120_Interfacedescription..., LAP120_Interfacedescription_UB... (+5 more) | Reserved |
| **bitfield0** | bitfield0 | X1 | M9-ADR-5.15_InterfaceDescripti..., u-blox-20-HPG-2.00_InterfaceDe..., u-blox-F10-SPG-6.00_InterfaceD... (+13 more) | bitfield: |

### Offset 18

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **reserved1** | reserved1 | U1[2] | F9-HPS-1.21_InterfaceDescripti..., F9-HPS120_Interfacedescription..., LAP120_Interfacedescription_UB... (+5 more) | Reserved |
| **reserved0** | reserved0 | U1[2] | M9-ADR-5.15_InterfaceDescripti..., u-blox-20-HPG-2.00_InterfaceDe..., u-blox-F10-SPG-6.00_InterfaceD... (+13 more) | Reserved |

---

## Full Structure Comparison

### Structure 1 (16 sources)

**Sources:** M9-ADR-5.15_InterfaceDescripti..., u-blox-20-HPG-2.00_InterfaceDe..., u-blox-F10-SPG-6.00_InterfaceD..., u-blox-F9-DBD-1.30_InterfaceDe..., u-blox-F9-HPG-1.50_InterfaceDe..., u-blox-F9-HPG-1.51_InterfaceDe..., u-blox-F9-HPG-L1L5-1.40_Interf..., u-blox-F9-HPS-1.30_InterfaceDe..., u-blox-F9-HPS-1.40_InterfaceDe..., u-blox-F9-LAP-1.30_InterfaceDe..., u-blox-F9-LAP-1.50_InterfaceDe..., u-blox-M10-SPG-5.10_InterfaceD..., u-blox-M10-SPG-5.30_InterfaceD..., u-blox-M9-MDR-2.16_InterfaceDe..., u-blox-M9-SPG-4.04_InterfaceDe..., u-blox-X20-HPG-2.02_InterfaceD...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | type | U1 | Message type (0x10 for this type) |
| 1 | version | U1 | Message version (0x00 for this version) |
| 2 | ref | X1 | Reference to be used to set time |
| 3 | leapSecs | I1 | Number of leap seconds since 1980 (or 0x80 = -128 ... |
| 4 | year | U2 | Year |
| 6 | month | U1 | Month, starting at 1 |
| 7 | day | U1 | Day, starting at 1 |
| 8 | hour | U1 | Hour, from 0 to 23 |
| 9 | minute | U1 | Minute, from 0 to 59 |
| 10 | second | U1 | Seconds, from 0 to 59 |
| 11 | bitfield0 | X1 | bitfield: |
| 12 | ns | U4 | Nanoseconds, from 0 to 999,999,999 |
| 16 | tAccS | U2 | Seconds part of time accuracy |
| 18 | reserved0 | U1[2] | Reserved |
| 20 | tAccNs | U4 | Nanoseconds part of time accuracy, from 0 to 999,9... |


### Structure 2 (8 sources)

**Sources:** F9-HPS-1.21_InterfaceDescripti..., F9-HPS120_Interfacedescription..., LAP120_Interfacedescription_UB..., M9-ADR-5.10_InterfaceDescripti..., M9-MDR-2.10_InterfaceDescripti..., u-blox-F9-HPG-1.13_InterfaceDe..., u-blox-F9-HPG-1.32_InterfaceDe..., u-blox_ZED-F9H_InterfaceDescri...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | type | U1 | Message type (0x10 for this type) |
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


---

## Adjudication Decision

- [x] Majority structure is correct
- [ ] Minority structure is correct
- [x] Both are valid (different firmware versions)
- [ ] Extraction error - needs re-extraction

**Decision:** Both structures are valid - field added without version bump.

**Rationale:** 
PDF review confirmed u-blox added `trustedSource` bitfield to offset 11 in newer firmware without incrementing the message version (remains 0x00).

- Older firmware: offset 11 = `reserved0 (U1)` - truly reserved
- Newer firmware: offset 11 = `bitfield0 (X1)` with `trustedSource` bit for replay attack detection

The offset 18 difference (`reserved1` vs `reserved0` naming) is just inconsistent naming of the same field.

**Recommendation:** Use Structure 1 (majority, with `bitfield0`) as canonical since it represents the latest firmware. Add annotation documenting the `trustedSource` addition. Already documented in `protocol_notes.json`.

**Canonical source:** X20-HPG-2.02, F9-HPG-1.51, M10-SPG-5.30 (latest firmware versions)
