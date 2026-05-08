# FlowPay Pipeline Validation Evidence

Generated at: `2026-05-03T21:50:30.190782+00:00`

## Overall Verdict: **PASS**

This evidence pack documents automated validation for the FlowPay real-time financial intelligence pipeline.

## Validation Standards

- Minimum tests per section: **10**
- Target pass rate per section: **90%**
- SLO (Service Level Objective) latency target: **P95 < 5.0s**
- Max cloud executions: **10**
- Dry run mode: **False**

## Results Summary

| Section | Tests | Passed | Pass Rate | Verdict |
|---|---:|---:|---:|---|
| Data Quality | 10 | 10 | 100% | PASS |
| Failure Handling | 10 | 10 | 100% | PASS |
| SLO + Decision Quality | 10 | 10 | 100% | PASS |

## SLO (Service Level Objective) Metrics

- Average latency: **1.6217s**
- P95 latency: **2.1482s**
- P95 latency target passed: **True**
- Decision accuracy: **100%**
- Availability: **100%**
- Infrastructure failures: **0**
- Business failures: **0**

## Confusion Matrix

```json
{
  "Normal": {
    "Normal": 4
  },
  "Guarded": {
    "Guarded": 3
  },
  "Defensive": {
    "Defensive": 2
  },
  "Critical": {
    "Critical": 1
  }
}
```

## Generated Evidence Files

- `data_quality_results.json`
- `failure_handling_results.json`
- `slo_and_decision_quality_results.json`
- `test_run_summary.json`
- `test_run_summary.md`

## Portfolio Claim

> FlowPay was validated with automated production-style tests covering data quality, failure handling, infrastructure reliability, SLO latency, decision quality, severity/MRS alignment, and action/severity alignment.