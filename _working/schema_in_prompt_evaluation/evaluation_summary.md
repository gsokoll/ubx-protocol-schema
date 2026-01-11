# Schema-in-Prompt Evaluation Report

**Generated**: 2026-01-08T23:50:09.289298+00:00

## Summary

### Extraction Performance

| Metric | Value |
|--------|-------|
| Total Attempted | 304 |
| Successful | 304 |
| Failed | 0 |
| Success Rate | 100.0% |
| Avg Time | 0.0s |
| Avg Attempts | 1.00 |
| Retry Rate | 0.0% |

### Agreement Improvement

| Metric | Value |
|--------|-------|
| Messages Compared | 12 |
| Avg Old Agreement | 69.9% |
| Avg New Agreement | 69.6% |
| **Improvement** | **-0.3%** |
| Improved | 5 |
| Degraded | 6 |
| Unchanged | 1 |

## Per-Message Results

| Message | Old | New | Δ | Status |
|---------|-----|-----|---|--------|
| UBX-NAV-SAT | 71% | 93% | +22% | majority |
| UBX-CFG-VALGET | 44% | 58% | +14% | split |
| UBX-ACK-ACK | 93% | 100% | +7% | unanimous |
| UBX-NAV-STATUS | 72% | 79% | +6% | majority |
| UBX-MON-HW | 38% | 39% | +1% | split |
| UBX-ACK-NAK | 100% | 100% | +0% | unanimous |
| UBX-MON-VER | 56% | 54% | -2% | split |
| UBX-RXM-SFRBX | 73% | 70% | -3% | split |
| UBX-NAV-PVT | 83% | 75% | -8% | majority |
| UBX-RXM-RAWX | 79% | 70% | -9% | split |
| UBX-NAV-RELPOSNED | 100% | 90% | -10% | majority |
| UBX-CFG-VALSET | 29% | 8% | -21% | split |

## Group Analysis

Messages with multiple extraction groups (potential version differences or errors):

### UBX-CFG-VALGET

**5 groups** from 24 sources:

- **Group A**: 14 sources
- **Group B**: 4 sources
- **Group C**: 3 sources
- **Group D**: 2 sources
- **Group E**: 1 sources

### UBX-CFG-VALSET

**23 groups** from 25 sources:

- **Group A**: 2 sources
- **Group B**: 2 sources
- **Group C**: 1 sources
- **Group D**: 1 sources
- **Group E**: 1 sources
- **Group F**: 1 sources
- **Group G**: 1 sources
- **Group H**: 1 sources
- **Group I**: 1 sources
- **Group J**: 1 sources
- **Group K**: 1 sources
- **Group L**: 1 sources
- **Group M**: 1 sources
- **Group N**: 1 sources
- **Group O**: 1 sources
- **Group P**: 1 sources
- **Group Q**: 1 sources
- **Group R**: 1 sources
- **Group S**: 1 sources
- **Group T**: 1 sources
- **Group U**: 1 sources
- **Group V**: 1 sources
- **Group W**: 1 sources

### UBX-MON-HW

**6 groups** from 23 sources:

- **Group A**: 9 sources
- **Group B**: 7 sources
- **Group C**: 4 sources
- **Group D**: 1 sources
- **Group E**: 1 sources
- **Group F**: 1 sources

### UBX-MON-VER

**6 groups** from 28 sources:

- **Group A**: 15 sources
- **Group B**: 5 sources
- **Group C**: 3 sources
- **Group D**: 3 sources
- **Group E**: 1 sources
- **Group F**: 1 sources

### UBX-NAV-PVT

**4 groups** from 28 sources:

- **Group A**: 21 sources
- **Group B**: 4 sources
- **Group C**: 2 sources
- **Group D**: 1 sources

### UBX-NAV-RELPOSNED

**2 groups** from 21 sources:

- **Group A**: 19 sources
- **Group B**: 2 sources

### UBX-NAV-SAT

**2 groups** from 28 sources:

- **Group A**: 26 sources
- **Group B**: 2 sources

### UBX-NAV-STATUS

**4 groups** from 28 sources:

- **Group A**: 22 sources
- **Group B**: 4 sources
- **Group C**: 1 sources
- **Group D**: 1 sources

### UBX-RXM-RAWX

**6 groups** from 23 sources:

- **Group A**: 16 sources
- **Group B**: 2 sources
- **Group C**: 2 sources
- **Group D**: 1 sources
- **Group E**: 1 sources
- **Group F**: 1 sources

### UBX-RXM-SFRBX

**4 groups** from 20 sources:

- **Group A**: 14 sources
- **Group B**: 4 sources
- **Group C**: 1 sources
- **Group D**: 1 sources
