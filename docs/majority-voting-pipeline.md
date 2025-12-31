# Majority Voting Validation Pipeline

---

## Problem Statement

Claude LLM extracts UBX protocol message definitions from u-blox PDF manuals. We cannot guarantee 100% extraction accuracy, but we can exploit redundancy:

1. **Same message type appears in multiple PDFs** (across devices and firmware versions)
2. **Protocol version field** in most messages identifies which extractions should be identical
3. **Majority agreement** across independent extractions indicates correctness

---

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. EXTRACTION (existing)                                        │
│    Claude extracts from each PDF → per-manual JSON              │
│    Output: data/ubx/by-manual/*_anthropic.json                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. STRUCTURAL VALIDATION (new)                                  │
│    Per-extraction checks:                                       │
│    - Offsets are sequential (no gaps/overlaps)                  │
│    - Sizes match data types                                     │
│    - Field count matches payload length                         │
│    → On failure: AUTO RE-EXTRACT with error context in prompt   │
│    → Re-extraction includes: previous result + specific errors  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. GROUPING & FINGERPRINTING (new)                              │
│    For each message in each extraction:                         │
│    - Extract protocol version field value (if present)          │
│    - Compute structural fingerprint                             │
│    - Group by (message_name, protocol_version)                  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. VOTING & ADJUDICATION (new)                                  │
│    For each (message_name, protocol_version):                   │
│    - Count fingerprint occurrences                              │
│    - Majority fingerprint wins → canonical structure            │
│    - Minority fingerprints → flagged as extraction errors       │
│    - Generate confidence score                                  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. CANONICAL OUTPUT (new format)                                │
│    One JSON per (message_name, protocol_version):               │
│    - NAV-PVT-v0.json, NAV-PVT-v1.json, etc.                    │
│    - Include consensus metadata for incremental updates         │
│    - Include confidence score and source provenance             │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. OUTLIER RE-EXTRACTION (iterative refinement)                 │
│    For messages without consensus:                              │
│    - Identify outlier extractions from discrepancy report       │
│    - Re-extract with consensus fields as reference              │
│    - Update extraction files and re-run validation              │
│    - Repeat until consensus achieved or confirmed different     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Re-extraction Workflow

When validation identifies outliers (extractions that differ from consensus), use targeted re-extraction:

```bash
# 1. Run validation to generate discrepancy report
uv run python scripts/validate_majority.py --extractions-dir data/ubx/by-manual --verbose

# 2. Re-extract outliers with consensus context
uv run python scripts/reextract_outliers.py

# 3. Re-run validation to check improvement
uv run python scripts/validate_majority.py --extractions-dir data/ubx/by-manual --verbose
```

The re-extraction script:
1. Reads `analysis_reports/discrepancy_report.json` for outlier list
2. For each outlier, provides Claude with:
   - The consensus field structure as reference
   - The specific discrepancy to fix
   - Fresh PDF pages for the message
3. Updates the extraction file with corrected result

**Prompt hints** in `src/extraction/prompts.py` provide additional guidance for challenging messages:
- Version variants (MON-GNSS, NAV-RELPOSNED)
- Array fields that might be split incorrectly (MGA-INI-TIME-*)
- Multi-variant messages (LOG-FINDTIME, RXM-RLM)

---

## Adjudication Workflow

When messages cannot reach consensus due to legitimate protocol differences (not extraction errors):

```bash
# 1. Generate adjudication reports for no-consensus messages
uv run python scripts/generate_adjudication_reports.py

# 2. Review reports in analysis_reports/adjudication/
#    - Compare field structures across sources
#    - Check PDF pages to verify differences are real
#    - Document decision in the report

# 3. Update protocol_notes.json with:
#    - Message name and protocol version
#    - Issue description
#    - Canonical source (prefer latest firmware)
#    - List of older and newer manuals

# 4. Generate validated JSON for adjudicated messages
uv run python scripts/generate_adjudicated_messages.py
```

**Adjudication policy:** Always prefer latest firmware version as canonical source.

---

## Key Design Decisions

### 1. Per-Extraction Canonicalization
**Decision:** Minimal — structural validation + field name normalization only.  
**Rationale:** Don't resolve naming conflicts until after voting; keeps comparison clean.

### 2. Missing Version Field
**Decision:** Treat as protocol version 0 (implicit).  
**Rationale:** Allows "same version" comparison logic to still apply for older messages.

### 3. Unit Handling in Voting
**Decision:**
- Different units (e.g., seconds vs hours) = **discrepancy** (counts against agreement)
- Missing vs present unit = **ignore** (doesn't affect fingerprint)

**Rationale:** Actual unit differences indicate extraction error; missing units are PDF omissions.

### 4. Cross-Version Comparison
**Decision:** We do **NOT** compare across different protocol versions.  
**Rationale:** Different versions are expected to differ. We only vote within same `(message_name, protocol_version)` group.

### 5. Voting Threshold
**Decision:** 75% agreement required for consensus (configurable).  
**Rationale:** 3 out of 4 agreeing sources is reasonable minimum.

### 6. Fingerprint Definition
**Decision:** Hash of structural elements only:
```python
fingerprint = hash([
    (field.name_normalized, field.byte_offset, field.data_type, field.size)
    for field in sorted(fields, key=lambda f: f.byte_offset)
])
```

**Includes:** name (normalized), offset, data_type, size  
**Excludes:** description, unit (for voting), scale, reserved flag, bitfield details

### 7. Output Format with Provenance
**Decision:** Include voting metadata for incremental updates:
```json
{
  "name": "UBX-NAV-PVT",
  "protocol_version": 0,
  "fingerprint": "a1b2c3d4...",
  "consensus": {
    "sources": ["F9-HPG-1.51", "F9-HPG-1.50", "M10-SPG-5.30"],
    "agreement_count": 14,
    "total_count": 15,
    "confidence": 0.93,
    "last_validated": "2025-12-29",
    "outliers": [
      {"source": "F9-DBD-1.30", "fingerprint": "x9y8z7...", "discrepancy": "..."}
    ]
  },
  "fields": [...]
}
```

**Rationale:** Enables incremental validation when new manuals are added.

### 8. Structural Validation with Auto Re-extraction
**Decision:** When structural validation fails (overlaps, invalid types), automatically re-submit to Claude with:
1. The previous failed extraction as context
2. Explicit list of errors that need fixing
3. Guidance to pay attention to offsets and sizes

**Prompt template:**
```
Re-extract message {name} from the PDF pages.

IMPORTANT: The previous extraction had structural errors that must be fixed:

ERROR: Field 'reserved0' at offset 5 overlaps with previous field (expected offset >= 8)
WARNING: Gap of 2 bytes before field 'flags' at offset 10

Previous extraction for reference (contains errors):
  offset 0: version (U1)
  offset 1: type (U1)
  ...

Please carefully re-extract all fields with correct byte offsets.
```

**Rationale:** Leverages Claude's strength at validation/correction over extraction from scratch.

### 9. Single-Source Messages
**Decision:** For messages with no comparison baseline, implement optional self-verification:
1. First extraction with normal prompt
2. Verification pass: show extraction + PDF, ask for field-by-field verification
3. Mark as `confidence: "single_source_verified"`

**Status:** Deferred to future implementation after core pipeline works.

---

## Future Workflows Supported

### A. New Manual Version for Existing Device
1. Extract from new manual only
2. For each message, compute fingerprint
3. Look up existing canonical by `(message_name, protocol_version)`
4. If fingerprint matches → increment `agreement_count`, add to `sources`
5. If fingerprint differs → flag for review, add to `outliers`
6. If message is new → create new canonical with single source, low confidence

### B. New Device Family
1. Extract all messages from new device's manual
2. Compare each against existing canonicals
3. Existing messages get additional source (increases confidence)
4. New messages flagged as single-source (low confidence, needs verification)

### C. Re-analysis with Updated Schema/LLM
1. Re-run extraction on all manuals with new model/prompts
2. Re-run full voting pipeline
3. Compare new canonicals against previous
4. Flag any regressions for review

---

## Implementation Plan

| Step | Status | Files |
|------|--------|-------|
| Create feature branch | ✅ Complete | - |
| Structural fingerprinting module | ✅ Complete | `src/validation/fingerprint.py` |
| Version field detection | ✅ Complete | `src/validation/version_detect.py` |
| Grouping logic | ✅ Complete | `src/validation/grouping.py` |
| Voting/adjudication module | ✅ Complete | `src/validation/voting.py` |
| Discrepancy report generation | ✅ Complete | `src/validation/report.py` |
| Output format with provenance | ✅ Complete | `src/validation/output.py` |
| Structural validation + auto re-extract | ✅ Complete | `src/validation/structural.py` |
| Main validation script | ✅ Complete | `scripts/validate_majority.py` |
| Outlier re-extraction script | ✅ Complete | `scripts/reextract_outliers.py` |
| Prompt hints for complex messages | ✅ Complete | `src/extraction/prompts.py` |
| Adjudication report generator | ✅ Complete | `scripts/generate_adjudication_reports.py` |
| Adjudicated message generator | ✅ Complete | `scripts/generate_adjudicated_messages.py` |
| Protocol notes for known issues | ✅ Complete | `data/ubx/validated/protocol_notes.json` |
| Self-verification for single-source | ⏳ Future | `src/validation/self_verify.py` |

---

## Configuration

```python
VALIDATION_CONFIG = {
    "voting_threshold": 0.75,          # 75% agreement required
    "min_sources_for_consensus": 3,    # At least 3 agreeing sources
    "fingerprint_includes": ["name", "byte_offset", "data_type", "size"],
    "fingerprint_excludes": ["description", "scale", "bitfield"],
    "unit_comparison": "strict_if_both_present",  # Ignore if one missing
}
```

---

## Resolved Questions

1. **Version field detection:** Heuristic detection based on field name "version" at offset 0-1 with type U1.
   - Messages WITH version field are treated as different format than those WITHOUT
   - Version value extracted from description (e.g., "0x02 for this version")

2. **Bitfield details in fingerprint:** Excluded (structural match is sufficient)

3. **Reserved field naming:** Field names included in fingerprint as-is

## Known Limitations

1. **Protocol evolution without version bump:** Some messages (e.g., MGA-INI-TIME-UTC) had fields added to previously reserved bytes without incrementing the version field. These show as no-consensus but the majority (newer manuals) is correct.

2. **Single-source messages:** 47 messages appear in only one manual and cannot be validated by consensus.

---

## References

- `data/ubx/validated/protocol_notes.json` — Documented protocol inconsistencies
- `analysis_reports/discrepancy_report.json` — Current validation outliers
- `src/extraction/prompts.py` — Prompt hints for challenging messages
