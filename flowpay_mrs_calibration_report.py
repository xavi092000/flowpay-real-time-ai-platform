import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Dict, List

import pandas as pd

from flowpay_quant_engine import compute_quant_decision


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "calibration"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

VALID_SEVERITIES = ["Normal", "Guarded", "Defensive", "Critical"]

EXPECTED_MRS_RANGES = {
    "Normal": (0, 24.99),
    "Guarded": (25, 49.99),
    "Defensive": (50, 74.99),
    "Critical": (75, float("inf")),
}


def synthetic_calibration_events() -> List[Dict[str, Any]]:
    scenarios = []

    templates = [
        ("normal_low_risk", "buy", 67000, 1.0, 3, 650000, 640000),
        ("normal_balanced", "sell", 67000, 1.0, 4, 620000, 630000),
        ("guarded_sell_pressure", "sell", 66000, 5.0, 15, 420000, 650000),
        ("guarded_spread_widening", "sell", 65500, 4.5, 20, 390000, 670000),
        ("defensive_liquidity_stress", "sell", 64000, 9.0, 35, 150000, 750000),
        ("defensive_execution_risk", "sell", 63500, 8.0, 40, 120000, 800000),
        ("critical_crash", "sell", 60000, 25.0, 90, 50000, 950000),
        ("critical_extreme_imbalance", "sell", 59000, 30.0, 110, 30000, 1_000_000),
    ]

    counter = 1

    for name, side, base_price, volume, spread_bps, bid_depth, ask_depth in templates:
        for shock in [0.98, 1.00, 1.02]:
            price = base_price * shock
            spread = price * spread_bps / 10_000

            scenarios.append({
                "scenario": name,
                "event_id": f"cal_{counter:04d}",
                "timestamp": f"2026-04-28T10:{counter:02d}:00Z",
                "symbol": "BTC-USD",
                "side": side,
                "price": price,
                "volume": volume,
                "bid": price - spread,
                "ask": price + spread,
                "bid_depth": bid_depth,
                "ask_depth": ask_depth,
            })

            counter += 1

    return scenarios


def normalize_decision(decision: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "mrs": decision.get("mrs", decision.get("market_risk_score")),
        "severity": decision.get("severity"),
        "action_bundle": decision.get("action_bundle", decision.get("recommended_action")),
    }


def validate_mrs(mrs: Any) -> bool:
    try:
        value = float(mrs)
        return not math.isnan(value) and value >= 0
    except (TypeError, ValueError):
        return False


def validate_severity(severity: Any) -> bool:
    return severity in VALID_SEVERITIES


def range_check(severity: str, mrs: float) -> bool:
    low, high = EXPECTED_MRS_RANGES[severity]
    return low <= mrs <= high


def run_calibration_sample() -> pd.DataFrame:
    rows = []

    for event in synthetic_calibration_events():
        decision = compute_quant_decision([event])
        normalized = normalize_decision(decision)

        mrs = normalized["mrs"]
        severity = normalized["severity"]
        action_bundle = normalized["action_bundle"]

        mrs_valid = validate_mrs(mrs)
        severity_valid = validate_severity(severity)

        if mrs_valid:
            mrs_float = float(mrs)
        else:
            mrs_float = None

        aligned = (
            mrs_valid
            and severity_valid
            and range_check(severity, mrs_float)
        )

        rows.append({
            "scenario": event["scenario"],
            "event_id": event["event_id"],
            "side": event["side"],
            "price": event["price"],
            "volume": event["volume"],
            "spread_bps": ((event["ask"] - event["bid"]) / event["price"]) * 10_000,
            "bid_depth": event["bid_depth"],
            "ask_depth": event["ask_depth"],
            "mrs": mrs_float,
            "severity": severity,
            "action_bundle": action_bundle,
            "mrs_valid": mrs_valid,
            "severity_valid": severity_valid,
            "mrs_severity_aligned": aligned,
        })

    return pd.DataFrame(rows)


def summarize_by_severity(df: pd.DataFrame) -> List[Dict[str, Any]]:
    summaries = []

    for severity in VALID_SEVERITIES:
        subset = df[df["severity"] == severity].copy()

        if subset.empty:
            summaries.append({
                "severity": severity,
                "count": 0,
                "note": "No samples classified in this severity.",
            })
            continue

        mrs_values = subset["mrs"].dropna().tolist()

        summaries.append({
            "severity": severity,
            "count": int(len(subset)),
            "mrs_min": round(float(min(mrs_values)), 2) if mrs_values else None,
            "mrs_avg": round(float(mean(mrs_values)), 2) if mrs_values else None,
            "mrs_max": round(float(max(mrs_values)), 2) if mrs_values else None,
            "mrs_std": round(float(stdev(mrs_values)), 2) if len(mrs_values) > 1 else 0.0,
            "alignment_rate": round(float(subset["mrs_severity_aligned"].mean()), 4),
            "expected_range": EXPECTED_MRS_RANGES[severity],
        })

    return summaries


def detect_calibration_issues(df: pd.DataFrame) -> List[str]:
    issues = []

    if not df["mrs_valid"].all():
        issues.append("Some MRS values are missing, non-numeric, NaN, or negative.")

    if not df["severity_valid"].all():
        issues.append("Some severity values are outside the approved taxonomy.")

    alignment_rate = df["mrs_severity_aligned"].mean()
    if alignment_rate < 0.95:
        issues.append(
            f"MRS/severity alignment is below target: {alignment_rate:.2%}. "
            "Review severity thresholds or compute_quant_decision output mapping."
        )

    severity_counts = Counter(df["severity"])
    missing_severities = [sev for sev in VALID_SEVERITIES if severity_counts.get(sev, 0) == 0]

    if missing_severities:
        issues.append(f"No calibration samples classified as: {missing_severities}")

    return issues


def generate_markdown_report(evidence: Dict[str, Any]) -> None:
    lines = [
        "# FlowPay MRS Calibration Report",
        "",
        "## Purpose",
        "",
        "This report validates whether MRS (Market Risk Score) outputs are numerically valid and aligned with severity categories.",
        "",
        "## What this validates",
        "",
        "- MRS numeric validity",
        "- Severity taxonomy validity",
        "- MRS/severity range alignment",
        "- Distribution of MRS by severity",
        "",
        "## What this does not validate",
        "",
        "- Real market alpha",
        "- True order-book execution",
        "- Live production drift over months",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(evidence["summary"], indent=2),
        "```",
        "",
        "## Calibration by Severity",
        "",
        "```json",
        json.dumps(evidence["severity_summary"], indent=2),
        "```",
        "",
        "## Issues",
        "",
    ]

    issues = evidence["issues"]

    if issues:
        for issue in issues:
            lines.append(f"- {issue}")
    else:
        lines.append("- No major calibration issues detected.")

    (OUTPUT_DIR / "flowpay_mrs_calibration_report.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def main() -> None:
    print("\nFLOWPAY MRS CALIBRATION REPORT")
    print("=" * 80)

    df = run_calibration_sample()
    severity_summary = summarize_by_severity(df)
    issues = detect_calibration_issues(df)

    summary = {
        "validation_type": "MRS calibration sanity report",
        "total_samples": int(len(df)),
        "mrs_valid_rate": round(float(df["mrs_valid"].mean()), 4),
        "severity_valid_rate": round(float(df["severity_valid"].mean()), 4),
        "mrs_severity_alignment_rate": round(float(df["mrs_severity_aligned"].mean()), 4),
        "verdict": "PASS" if not issues else "FAIL",
    }

    evidence = {
        "summary": summary,
        "severity_summary": severity_summary,
        "issues": issues,
        "records": df.to_dict(orient="records"),
    }

    df.to_csv(OUTPUT_DIR / "flowpay_mrs_calibration_records.csv", index=False)

    with open(OUTPUT_DIR / "flowpay_mrs_calibration_summary.json", "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)

    generate_markdown_report(evidence)

    print(json.dumps(summary, indent=2))

    if issues:
        print("\nIssues:")
        for issue in issues:
            print(f"- {issue}")

    print("\nSaved:")
    print(OUTPUT_DIR / "flowpay_mrs_calibration_records.csv")
    print(OUTPUT_DIR / "flowpay_mrs_calibration_summary.json")
    print(OUTPUT_DIR / "flowpay_mrs_calibration_report.md")


if __name__ == "__main__":
    main()