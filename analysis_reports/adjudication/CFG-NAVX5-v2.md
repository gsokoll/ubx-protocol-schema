# Adjudication Report: UBX-CFG-NAVX5 v2

**Generated:** 2025-12-30 12:13
**Total sources:** 7
**Unique structures:** 3

---

## Summary

**Majority structure:** 4/7 sources
- Sources: u-blox-F9-HPG-1.13_InterfaceDe..., u-blox-F9-HPG-1.32_InterfaceDe..., u-blox-M9-SPG-4.04_InterfaceDe..., u-blox_ZED-F9H_InterfaceDescri...

**Minority structures:**
- 2 sources: u-blox-F9-HPG-1.50_InterfaceDe..., u-blox-F9-HPG-1.51_InterfaceDe...
- 1 sources: u-blox-F9-HPG-L1L5-1.40_Interf...

---

## Field Differences

### Offset 10

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **minSVs** | minSVs | U1 | u-blox-F9-HPG-1.13_InterfaceDe..., u-blox-F9-HPG-1.32_InterfaceDe..., u-blox-F9-HPG-1.50_InterfaceDe... (+3 more) | Minimum number of satellites for navigat... |
| **minSvs** | minSvs | U1 | u-blox-F9-HPG-L1L5-1.40_Interf... | Minimum number of satellites for navigat... |

### Offset 11

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **maxSVs** | maxSVs | U1 | u-blox-F9-HPG-1.13_InterfaceDe..., u-blox-F9-HPG-1.32_InterfaceDe..., u-blox-F9-HPG-1.50_InterfaceDe... (+3 more) | Maximum number of satellites for navigat... |
| **maxSvs** | maxSvs | U1 | u-blox-F9-HPG-L1L5-1.40_Interf... | Maximum number of satellites for navigat... |

### Offset 28

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **reserved6** | reserved6 | U1[2] | u-blox-F9-HPG-1.13_InterfaceDe..., u-blox-F9-HPG-1.32_InterfaceDe..., u-blox-F9-HPG-L1L5-1.40_Interf... (+2 more) |  |
| **reserved6** | reserved6 | U1 | u-blox-F9-HPG-1.50_InterfaceDe..., u-blox-F9-HPG-1.51_InterfaceDe... |  |

### Offset 32

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **reserved7** | reserved7 | U1[4] | u-blox-F9-HPG-1.13_InterfaceDe..., u-blox-F9-HPG-1.32_InterfaceDe..., u-blox-F9-HPG-L1L5-1.40_Interf... (+2 more) |  |
| **reserved8** | reserved8 | U1[4] | u-blox-F9-HPG-1.50_InterfaceDe..., u-blox-F9-HPG-1.51_InterfaceDe... |  |

### Offset 36

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **reserved8** | reserved8 | U1[3] | u-blox-F9-HPG-1.13_InterfaceDe..., u-blox-F9-HPG-1.32_InterfaceDe..., u-blox-F9-HPG-L1L5-1.40_Interf... (+2 more) |  |
| **reserved9** | reserved9 | U1[3] | u-blox-F9-HPG-1.50_InterfaceDe..., u-blox-F9-HPG-1.51_InterfaceDe... |  |

---

## Full Structure Comparison

### Structure 1 (4 sources)

**Sources:** u-blox-F9-HPG-1.13_InterfaceDe..., u-blox-F9-HPG-1.32_InterfaceDe..., u-blox-M9-SPG-4.04_InterfaceDe..., u-blox_ZED-F9H_InterfaceDescri...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | version | U2 | Message version (0x0002 for this version) |
| 2 | mask1 | X2 | First parameters bitmask. Only the flagged paramet... |
| 4 | mask2 | X4 | Second parameters bitmask. Only the flagged parame... |
| 8 | reserved0 | U1[2] |  |
| 10 | minSVs | U1 | Minimum number of satellites for navigation |
| 11 | maxSVs | U1 | Maximum number of satellites for navigation |
| 12 | minCNO | U1 | Minimum satellite signal level for navigation |
| 13 | reserved1 | U1 |  |
| 14 | iniFix3D | U1 | 1 = initial fix must be 3D |
| 15 | reserved2 | U1[2] |  |
| 17 | ackAiding | U1 | 1 = issue acknowledgements for assistance message ... |
| 18 | wknRollover | U2 | GPS week rollover number; GPS week numbers will be... |
| 20 | sigAttenCompMode | U1 | Only supported on certain products |
| 21 | reserved3 | U1 |  |
| 22 | reserved4 | U1[2] |  |
| 24 | reserved5 | U1[2] |  |
| 26 | usePPP | U1 | 1 = use Precise Point Positioning (only available ... |
| 27 | aopCfg | U1 | AssistNow Autonomous configuration |
| 28 | reserved6 | U1[2] |  |
| 30 | aopOrbMaxErr | U2 | Maximum acceptable (modeled) AssistNow Autonomous ... |
| 32 | reserved7 | U1[4] |  |
| 36 | reserved8 | U1[3] |  |
| 39 | useAdr | U1 | Only supported on certain products |


### Structure 2 (2 sources)

**Sources:** u-blox-F9-HPG-1.50_InterfaceDe..., u-blox-F9-HPG-1.51_InterfaceDe...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | version | U2 | Message version (0x0002 for this version) |
| 2 | mask1 | X2 | First parameters bitmask. Only the flagged paramet... |
| 4 | mask2 | X4 | Second parameters bitmask. Only the flagged parame... |
| 8 | reserved0 | U1[2] |  |
| 10 | minSVs | U1 | Minimum number of satellites for navigation |
| 11 | maxSVs | U1 | Maximum number of satellites for navigation |
| 12 | minCNO | U1 | Minimum satellite signal level for navigation |
| 13 | reserved1 | U1 |  |
| 14 | iniFix3D | U1 | 1 = initial fix must be 3D |
| 15 | reserved2 | U1[2] |  |
| 17 | ackAiding | U1 | 1 = issue acknowledgements for assistance message ... |
| 18 | wknRollover | U2 | GPS week rollover number; GPS week numbers will be... |
| 20 | sigAttenCompMode | U1 | Only supported on certain products |
| 21 | reserved3 | U1 |  |
| 22 | reserved4 | U1[2] |  |
| 24 | reserved5 | U1[2] |  |
| 26 | usePPP | U1 | 1 = use Precise Point Positioning (only available ... |
| 27 | aopCfg | U1 | AssistNow Autonomous configuration |
| 28 | reserved6 | U1 |  |
| 29 | reserved7 | U1 |  |
| 30 | aopOrbMaxErr | U2 | Maximum acceptable (modeled) AssistNow Autonomous ... |
| 32 | reserved8 | U1[4] |  |
| 36 | reserved9 | U1[3] |  |
| 39 | useAdr | U1 | Only supported on certain products |


### Structure 3 (1 sources)

**Sources:** u-blox-F9-HPG-L1L5-1.40_Interf...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | version | U2 | Message version (0x0002 for this version) |
| 2 | mask1 | X2 | First parameters bitmask. Only the flagged paramet... |
| 4 | mask2 | X4 | Second parameters bitmask. Only the flagged parame... |
| 8 | reserved0 | U1[2] | Reserved |
| 10 | minSvs | U1 | Minimum number of satellites for navigation |
| 11 | maxSvs | U1 | Maximum number of satellites for navigation |
| 12 | minCNO | U1 | Minimum satellite signal level for navigation |
| 13 | reserved1 | U1 | Reserved |
| 14 | iniFix3D | U1 | 1 = initial fix must be 3D |
| 15 | reserved2 | U1[2] | Reserved |
| 17 | ackAiding | U1 | 1 = issue acknowledgements for assistance message ... |
| 18 | wknRollover | U2 | GPS week rollover number; GPS week numbers will be... |
| 20 | sigAttenCompMode | U1 | Only supported on certain products |
| 21 | reserved3 | U1 | Reserved |
| 22 | reserved4 | U1[2] | Reserved |
| 24 | reserved5 | U1[2] | Reserved |
| 26 | usePPP | U1 | 1 = use Precise Point Positioning (only available ... |
| 27 | aopCfg | U1 | AssistNow Autonomous configuration |
| 28 | reserved6 | U1[2] | Reserved |
| 30 | aopOrbMaxErr | U2 | Maximum acceptable (modeled) AssistNow Autonomous ... |
| 32 | reserved7 | U1[4] | Reserved |
| 36 | reserved8 | U1[3] | Reserved |
| 39 | useAdr | U1 | Only supported on certain products |


---

## Adjudication Decision

- [ ] Majority structure is correct
- [ ] Minority structure is correct
- [x] Both are valid (different firmware versions)
- [ ] Extraction error - needs re-extraction

**Decision:** Both structures are valid - protocol evolution without version bump.

**Rationale:** 
PDF review confirmed:
- F9-HPG-1.13 (older): offset 28 = `reserved6 (U1[2])` as 2-byte array
- F9-HPG-1.51 (newer): offset 28 = `reserved6 (U1)`, offset 29 = `reserved7 (U1)` as separate bytes

The reserved bytes were reorganized between firmware versions. Both extractions are correct for their respective firmware. The `minSVs` vs `minSvs` difference is just casing inconsistency.

**Recommendation:** Use Structure 2 (F9-HPG-1.50/1.51 - newest firmware) as canonical. Add annotation noting older firmware has different reserved field layout.

**Canonical source:** F9-HPG-1.51 (latest)
