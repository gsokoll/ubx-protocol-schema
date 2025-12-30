# Adjudication Report: UBX-RXM-PMREQ v0

**Generated:** 2025-12-30 12:13
**Total sources:** 18
**Unique structures:** 4

---

## Summary

**Majority structure:** 12/18 sources
- Sources: F9-HPS120_Interfacedescription..., M9-ADR-5.15_InterfaceDescripti..., u-blox-F10-SPG-6.00_InterfaceD..., u-blox-F9-DBD-1.30_InterfaceDe..., u-blox-F9-HPG-1.13_InterfaceDe......

**Minority structures:**
- 4 sources: u-blox-20-HPG-2.00_InterfaceDe..., u-blox-F9-HPG-L1L5-1.40_Interf..., u-blox-F9-HPS-1.40_InterfaceDe......
- 1 sources: M9-MDR-2.10_InterfaceDescripti...
- 1 sources: u-blox8-M8_ReceiverDescrProtSp...

---

## Field Differences

### Offset 0

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **version** | version | U1 | F9-HPS120_Interfacedescription..., M9-ADR-5.15_InterfaceDescripti..., M9-MDR-2.10_InterfaceDescripti... (+11 more) | Message version (0x00 for this version, ... |
| **duration** | duration | U4 | u-blox-20-HPG-2.00_InterfaceDe..., u-blox-F9-HPG-L1L5-1.40_Interf..., u-blox-F9-HPS-1.40_InterfaceDe... (+1 more) | Duration of the requested task. The maxi... |

### Offset 1

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **reserved0** | reserved0 | U1[3] | F9-HPS120_Interfacedescription..., M9-ADR-5.15_InterfaceDescripti..., M9-MDR-2.10_InterfaceDescripti... (+10 more) | Reserved (only in V1 format) |
| **reserved1** | reserved1 | U1[3] | u-blox8-M8_ReceiverDescrProtSp... | Reserved |

### Offset 4

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **duration** | duration | U4 | F9-HPS120_Interfacedescription..., M9-ADR-5.15_InterfaceDescripti..., u-blox-F10-SPG-6.00_InterfaceD... (+9 more) | Duration of the requested task, set to z... |
| **flags_v0** | flags_v0 | X4 | M9-MDR-2.10_InterfaceDescripti... | Task flags (version 0 only) |
| **flags** | flags | X4 | u-blox-20-HPG-2.00_InterfaceDe..., u-blox-F9-HPG-L1L5-1.40_Interf..., u-blox-F9-HPS-1.40_InterfaceDe... (+1 more) | task flags |
| **duration_v1** | duration_v1 | U4 | u-blox8-M8_ReceiverDescrProtSp... | Duration of the requested task. The maxi... |

### Offset 8

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **flags** | flags | X4 | F9-HPS120_Interfacedescription..., M9-ADR-5.15_InterfaceDescripti..., u-blox-F10-SPG-6.00_InterfaceD... (+9 more) | task flags |
| **flags_v1** | flags_v1 | X4 | M9-MDR-2.10_InterfaceDescripti..., u-blox8-M8_ReceiverDescrProtSp... | Task flags (version 1 only) |

---

## Full Structure Comparison

### Structure 1 (12 sources)

**Sources:** F9-HPS120_Interfacedescription..., M9-ADR-5.15_InterfaceDescripti..., u-blox-F10-SPG-6.00_InterfaceD..., u-blox-F9-DBD-1.30_InterfaceDe..., u-blox-F9-HPG-1.13_InterfaceDe..., u-blox-F9-HPG-1.51_InterfaceDe..., u-blox-F9-HPS-1.30_InterfaceDe..., u-blox-F9-LAP-1.30_InterfaceDe..., u-blox-M10-SPG-5.10_InterfaceD..., u-blox-M10-SPG-5.30_InterfaceD..., u-blox-X20-HPG-2.02_InterfaceD..., u-blox_ZED-F9H_InterfaceDescri...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | version | U1 | Message version (0x00 for this version, only in V1... |
| 1 | reserved0 | U1[3] | Reserved (only in V1 format) |
| 4 | duration | U4 | Duration of the requested task, set to zero for in... |
| 8 | flags | X4 | task flags |
| 12 | wakeupSources | X4 | Configure pins to wake up the receiver. The receiv... |


### Structure 2 (4 sources)

**Sources:** u-blox-20-HPG-2.00_InterfaceDe..., u-blox-F9-HPG-L1L5-1.40_Interf..., u-blox-F9-HPS-1.40_InterfaceDe..., u-blox-M9-SPG-4.04_InterfaceDe...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | duration | U4 | Duration of the requested task. The maximum suppor... |
| 4 | flags | X4 | task flags |


### Structure 3 (1 sources)

**Sources:** M9-MDR-2.10_InterfaceDescripti...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | version | U1 | Message version (0x00 for version 1, absent in ver... |
| 1 | reserved0 | U1[3] | Reserved (only in version 1) |
| 4 | duration | U4 | Duration of the requested task, set to zero for in... |
| 4 | flags_v0 | X4 | Task flags (version 0 only) |
| 8 | flags_v1 | X4 | Task flags (version 1 only) |
| 12 | wakeupSources | X4 | Configure pins to wake up the receiver. The receiv... |


### Structure 4 (1 sources)

**Sources:** u-blox8-M8_ReceiverDescrProtSp...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | duration | U4 | Duration of the requested task. The maximum suppor... |
| 0 | version | U1 | Message version (0x00 for this version) |
| 1 | reserved1 | U1[3] | Reserved |
| 4 | flags | X4 | task flags (see graphic below) |
| 4 | duration_v1 | U4 | Duration of the requested task. The maximum suppor... |
| 8 | flags_v1 | X4 | task flags (see graphic below) |
| 12 | wakeupSources | X4 | Configure pins to wake up the receiver. The receiv... |


---

## Adjudication Decision

- [ ] Majority structure is correct
- [ ] Minority structure is correct
- [x] Both are valid (different firmware versions)
- [x] Extraction error - needs re-extraction (Structures 3 & 4)

**Decision:** Mixed - Structures 1 and 2 are valid but represent DIFFERENT message versions incorrectly grouped together. Structures 3 and 4 are extraction errors.

**Rationale:** 
RXM-PMREQ has TWO distinct message formats that should NOT be grouped together:

- **V0 format (8 bytes):** `duration@0, flags@4` - NO version field (Structure 2)
- **V1 format (16 bytes):** `version@0, reserved0[3]@1, duration@4, flags@8, wakeupSources@12` (Structure 1)

The version detection is grouping both as "v0" because:
- V0 format has no version field → detected as v0
- V1 format has version field with value 0x00 → also detected as v0

**Structure 3 (M9-MDR-2.10):** Extraction error - has both `flags_v0` and `flags_v1` suggesting Claude extracted both variants into one message.

**Structure 4 (M8):** Extraction error - has duplicate fields at offset 0 and offset 4.

**Recommendation:** 
1. The version detection logic should treat "has version field" vs "no version field" as different formats (already implemented but not working correctly here)
2. Re-extract M9-MDR-2.10 and M8 to fix extraction errors
3. Structure 1 (with version field, 16 bytes) should be canonical - this is the format in latest firmware (F9-HPG-1.51, X20-HPG-2.02)
4. Structure 2 (8 bytes, no version field) is legacy V0 format for older devices

**Canonical source:** F9-HPG-1.51, X20-HPG-2.02 (latest firmware - use Structure 1 with version field)
