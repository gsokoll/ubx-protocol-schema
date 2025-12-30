# Adjudication Report: UBX-SEC-SIG v1

**Generated:** 2025-12-30 12:13
**Total sources:** 7
**Unique structures:** 3

---

## Summary

**Majority structure:** 5/7 sources
- Sources: F9-HPS-1.21_InterfaceDescripti..., M9-ADR-5.15_InterfaceDescripti..., u-blox-F9-DBD-1.30_InterfaceDe..., u-blox-F9-HPG-L1L5-1.40_Interf..., u-blox-F9-HPS-1.30_InterfaceDe...

**Minority structures:**
- 1 sources: u-blox-F10-SPG-6.00_InterfaceD...
- 1 sources: u-blox-F9-HPS-1.40_InterfaceDe...

---

## Field Differences

### Offset 1

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **reserved0** | reserved0 | U1[3] | F9-HPS-1.21_InterfaceDescripti..., M9-ADR-5.15_InterfaceDescripti..., u-blox-F9-DBD-1.30_InterfaceDe... (+3 more) | Reserved |
| **sigSecFlags** | sigSecFlags | X1 | u-blox-F10-SPG-6.00_InterfaceD... | Signal security flags |

### Offset 4

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **jamFlags** | jamFlags | X1 | F9-HPS-1.21_InterfaceDescripti..., M9-ADR-5.15_InterfaceDescripti..., u-blox-F10-SPG-6.00_InterfaceD... (+3 more) | Information related to jamming/interfere... |
| **jammingState** | jammingState | U2 | u-blox-F9-HPS-1.40_InterfaceDe... | Jamming/interference state |

### Offset 8

| Variant | Name | Type | Sources | Description |
|---------|------|------|---------|-------------|
| **spfFlags** | spfFlags | X1 | F9-HPS-1.21_InterfaceDescripti..., M9-ADR-5.15_InterfaceDescripti..., u-blox-F10-SPG-6.00_InterfaceD... (+3 more) | Information related to GNSS spoofing |
| **spoofingState** | spoofingState | U3 | u-blox-F9-HPS-1.40_InterfaceDe... | Spoofing state |

---

## Full Structure Comparison

### Structure 1 (5 sources)

**Sources:** F9-HPS-1.21_InterfaceDescripti..., M9-ADR-5.15_InterfaceDescripti..., u-blox-F9-DBD-1.30_InterfaceDe..., u-blox-F9-HPG-L1L5-1.40_Interf..., u-blox-F9-HPS-1.30_InterfaceDe...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | version | U1 | Message version (0x01 for this version) |
| 1 | reserved0 | U1[3] | Reserved |
| 4 | jamFlags | X1 | Information related to jamming/interference |
| 5 | reserved1 | U1[3] | Reserved |
| 8 | spfFlags | X1 | Information related to GNSS spoofing |
| 9 | reserved2 | U1[3] | Reserved |


### Structure 2 (1 sources)

**Sources:** u-blox-F10-SPG-6.00_InterfaceD...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | version | U1 | Message version (0x01 for this version) |
| 1 | sigSecFlags | X1 | Signal security flags |
| 2 | reserved0 | U1 |  |
| 3 | jamNumCentFreqs | U1 | Number of center frequencies for jamming detection |
| 4 | jamFlags | X1 | Information related to jamming/interference |
| 5 | reserved1 | U1[3] |  |
| 8 | spfFlags | X1 | Information related to GNSS spoofing |
| 9 | reserved2 | U1[3] |  |


### Structure 3 (1 sources)

**Sources:** u-blox-F9-HPS-1.40_InterfaceDe...

| Offset | Name | Type | Description |
|--------|------|------|-------------|
| 0 | version | U1 | Message version (0x01 for this version) |
| 1 | reserved0 | U1[3] | Reserved |
| 4 | jamDetEnabled | U1 | Flag indicates whether jamming/interference detect... |
| 4 | jammingState | U2 | Jamming/interference state |
| 5 | reserved1 | U1[3] | Reserved |
| 8 | spfDetEnabled | U1 | Flag indicates whether spoofing detection is enabl... |
| 8 | spoofingState | U3 | Spoofing state |
| 9 | reserved2 | U1[3] | Reserved |


---

## Adjudication Decision

- [x] Majority structure is correct
- [ ] Minority structure is correct
- [x] Both are valid (different firmware versions)
- [x] Extraction error - needs re-extraction (Structure 3)

**Decision:** Mixed - Structure 1 (majority) and Structure 2 are valid firmware variants. Structure 3 is an extraction error.

**Rationale:** 
- **Structure 1 (5 sources):** v1 format with `reserved0[3]` at offset 1 - older v1 firmware
- **Structure 2 (F10-SPG-6.00):** v1 format with `sigSecFlags` at offset 1 - newer v1 firmware that added security flags
- **Structure 3 (F9-HPS-1.40):** Extraction error - has duplicate fields at same offsets (jamDetEnabled and jammingState both at offset 4)

The v1 structure evolved to add `sigSecFlags` and `jamNumCentFreqs` in some firmware versions.

**Recommendation:** 
1. Re-extract F9-HPS-1.40 to fix Structure 3
2. Use Structure 2 (F10-SPG-6.00, with sigSecFlags) as canonical for v1 since it represents the latest firmware
3. Add annotation noting v1 structure varies between firmware versions

**Canonical source:** F10-SPG-6.00 (latest firmware with v1)
