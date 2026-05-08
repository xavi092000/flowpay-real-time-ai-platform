import json
import math
import time
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Tuple

import pandas as pd

from flowpay_quant_engine import compute_quant_decision


PROJECT_ROOT = Path(__file__).resolve().parent
INPUT_FILE = PROJECT_ROOT / "data" / "flowpay_30s_events.csv"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "event_replay_validation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

WINDOW_SECONDS = 30
SLO_LATENCY_SECONDS = 5.0

VALID_SEVERITIES = {"Normal", "Guarded", "Defensive", "Critical"}

EXPECTED_ACTIONS = {
    "Normal": {"monitor_only", "monitoring_bundle"},
    "Guarded": {"increase_monitoring", "early_warning_bundle"},
    "Defensive": {"defensive_bundle", "liquidity_rebalancing"},
    "Critical": {"critical_bundle", "risk_off_bundle", "emergency_review"},
}

MRS_RANGES = {
    "Normal": (0, 24.99),
    "Guarded": (25, 49.99),
    "Defensive": (50, 74.99),
    "Critical": (75, float("inf")),
}


def build_fallback_30s_events() -> pd.DataFrame:
    rows = []
    base_time = pd.Timestamp("2026-04-28T10:00:00Z")

    scenarios = [
        ("normal_market", "BTC-USD", "Normal", [67000, 67002, 67001], [1.0, 1.1, 1.0], [3, 3, 4]),
        ("guarded_sell_pressure", "BTC-USD", "Guarded", [67000, 66650, 66400], [3.0, 4.0, 4.5], [10, 12, 14]),
        ("defensive_liquidity_stress", "BTC-USD", "Defensive", [66000, 65000, 64200], [8.0, 8.5, 9.0], [25, 30, 35]),
        ("critical_crash", "BTC-USD", "Critical", [65000, 62000, 59000], [15.0, 20.0, 25.0], [50, 80, 100]),
        ("missing_data_adversarial", "BTC-USD", "INVALID", [65000, None, 64000], [2.0, 2.0, 2.0], [10, 10, 10]),
    ]

    event_counter = 1

    for scenario_name, symbol, expected_severity, prices, volumes, spreads in scenarios:
        for i, price in enumerate(prices):
            ts = base_time + pd.Timedelta(seconds=i * 10) + pd.Timedelta(minutes=len(rows))

            if price is None:
                bid = None
                ask = None
            else:
                spread_value = price * spreads[i] / 10_000
                bid = price - spread_value
                ask = price + spread_value

            rows.append({
                "scenario": scenario_name,
                "expected_severity": expected_severity,
                "event_id": f"evt_{event_counter:04d}",
                "timestamp": ts.isoformat(),
                "symbol": symbol,
                "side": "sell" if expected_severity in {"Guarded", "Defensive", "Critical"} else "buy",
                "price": price,
                "volume": volumes[i],
                "bid": bid,
                "ask": ask,
                "bid_depth": max(50_000, 600_000 - i * 120_000),
                "ask_depth": 600_000 + i * 120_000,
            })

            event_counter += 1

    return pd.DataFrame(rows)


def load_events() -> pd.DataFrame:
    if INPUT_FILE.exists():
        df = pd.read_csv(INPUT_FILE)
    else:
        df = build_fallback_30s_events()

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.sort_values(["scenario", "timestamp"]).reset_index(drop=True)
    return df


def validate_event_schema(events: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    required = {
        "event_id",
        "timestamp",
        "symbol",
        "side",
        "price",
        "volume",
        "bid",
        "ask",
        "bid_depth",
        "ask_depth",
    }

    errors = []

    for idx, event in enumerate(events):
        missing = required - set(event.keys())
        if missing:
            errors.append(f"event[{idx}] missing fields: {sorted(missing)}")
            continue

        if event["side"] not in {"buy", "sell"}:
            errors.append(f"event[{idx}] invalid side: {event['side']}")

        for numeric_field in ["price", "volume", "bid", "ask", "bid_depth", "ask_depth"]:
            value = event.get(numeric_field)
            if value is None or pd.isna(value):
                errors.append(f"event[{idx}] missing numeric field: {numeric_field}")
                continue

            try:
                value_float = float(value)
            except (TypeError, ValueError):
                errors.append(f"event[{idx}] non-numeric {numeric_field}: {value}")
                continue

            if value_float <= 0:
                errors.append(f"event[{idx}] {numeric_field} must be positive: {value_float}")

        if event.get("bid") is not None and event.get("ask") is not None:
            try:
                if float(event["bid"]) >= float(event["ask"]):
                    errors.append(f"event[{idx}] bid must be lower than ask")
            except (TypeError, ValueError):
                pass

    return len(errors) == 0, errors


def normalize_decision(decision: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "mrs": decision.get("mrs", decision.get("market_risk_score")),
        "severity": decision.get("severity"),
        "action_bundle": decision.get("action_bundle", decision.get("recommended_action")),
    }


def validate_decision_contract(decision: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors = []
    normalized = normalize_decision(decision)

    severity = normalized["severity"]
    mrs = normalized["mrs"]
    action_bundle = normalized["action_bundle"]

    if severity not in VALID_SEVERITIES:
        errors.append(f"Invalid severity: {severity}")

    try:
        mrs_float = float(mrs)
        if math.isnan(mrs_float) or mrs_float < 0:
            errors.append(f"Invalid MRS: {mrs}")
    except (TypeError, ValueError):
        errors.append(f"MRS missing or non-numeric: {mrs}")

    if not action_bundle:
        errors.append("Missing action_bundle / recommended_action")

    if severity in MRS_RANGES:
        low, high = MRS_RANGES[severity]
        try:
            mrs_float = float(mrs)
            if not (low <= mrs_float <= high):
                errors.append(f"MRS {mrs_float} outside expected range for {severity}: {low}-{high}")
        except (TypeError, ValueError):
            pass

    if severity in EXPECTED_ACTIONS and action_bundle not in EXPECTED_ACTIONS[severity]:
        errors.append(f"Action {action_bundle} not aligned with severity {severity}")

    return len(errors) == 0, errors


def split_into_30s_windows(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    windows = {}

    for scenario, scenario_df in df.groupby("scenario"):
        scenario_df = scenario_df.sort_values("timestamp").copy()

        start_time = scenario_df["timestamp"].min()
        scenario_df["window_id"] = (
            (scenario_df["timestamp"] - start_time).dt.total_seconds() // WINDOW_SECONDS
        ).astype(int)

        for window_id, window_df in scenario_df.groupby("window_id"):
            key = f"{scenario}_window_{window_id}"
            windows[key] = window_df.copy()

    return windows


def dataframe_to_events(df: pd.DataFrame) -> List[Dict[str, Any]]:
    events = []

    for _, row in df.iterrows():
        events.append({
            "event_id": str(row["event_id"]),
            "timestamp": row["timestamp"].isoformat(),
            "symbol": str(row["symbol"]),
            "side": str(row["side"]),
            "price": None if pd.isna(row["price"]) else float(row["price"]),
            "volume": None if pd.isna(row["volume"]) else float(row["volume"]),
            "bid": None if pd.isna(row["bid"]) else float(row["bid"]),
            "ask": None if pd.isna(row["ask"]) else float(row["ask"]),
            "bid_depth": None if pd.isna(row["bid_depth"]) else float(row["bid_depth"]),
            "ask_depth": None if pd.isna(row["ask_depth"]) else float(row["ask_depth"]),
        })

    return events


def run_window_test(window_name: str, window_df: pd.DataFrame) -> Dict[str, Any]:
    expected_severity = str(window_df["expected_severity"].iloc[0])
    events = dataframe_to_events(window_df)

    schema_valid, schema_errors = validate_event_schema(events)

    if not schema_valid:
        expected_invalid = expected_severity == "INVALID"

        return {
            "window": window_name,
            "expected_severity": expected_severity,
            "actual_severity": None,
            "mrs": None,
            "action_bundle": None,
            "schema_valid": False,
            "schema_errors": schema_errors,
            "decision_contract_valid": False,
            "decision_errors": [],
            "latency_seconds": 0.0,
            "slo_latency_passed": True,
            "test_passed": expected_invalid,
            "failure_type": "DATA_QUALITY" if expected_invalid else "UNEXPECTED_DATA_QUALITY_FAILURE",
        }

    start = time.perf_counter()
    raw_decision = compute_quant_decision(events)
    latency_seconds = time.perf_counter() - start

    normalized = normalize_decision(raw_decision)

    decision_valid, decision_errors = validate_decision_contract(raw_decision)

    actual_severity = normalized["severity"]
    mrs = normalized["mrs"]
    action_bundle = normalized["action_bundle"]

    severity_correct = actual_severity == expected_severity
    latency_passed = latency_seconds <= SLO_LATENCY_SECONDS

    test_passed = (
        expected_severity != "INVALID"
        and schema_valid
        and decision_valid
        and severity_correct
        and latency_passed
    )

    return {
        "window": window_name,
        "expected_severity": expected_severity,
        "actual_severity": actual_severity,
        "mrs": mrs,
        "action_bundle": action_bundle,
        "schema_valid": schema_valid,
        "schema_errors": schema_errors,
        "decision_contract_valid": decision_valid,
        "decision_errors": decision_errors,
        "latency_seconds": round(latency_seconds, 4),
        "slo_latency_passed": latency_passed,
        "severity_correct": severity_correct,
        "test_passed": test_passed,
        "failure_type": "NONE" if test_passed else "BUSINESS_OR_CONTRACT_FAILURE",
    }


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r["test_passed"])
    latencies = [r["latency_seconds"] for r in results if r["latency_seconds"] is not None]

    sorted_latencies = sorted(latencies)
    p95_latency = 0.0

    if sorted_latencies:
        index = math.ceil(0.95 * len(sorted_latencies)) - 1
        index = max(0, min(index, len(sorted_latencies) - 1))
        p95_latency = sorted_latencies[index]

    valid_contracts = sum(1 for r in results if r["decision_contract_valid"])
    correct_decisions = sum(1 for r in results if r.get("severity_correct") is True)

    return {
        "validation_type": "30-second event replay validation",
        "total_windows": total,
        "passed_windows": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "decision_contract_rate": round(valid_contracts / total, 4) if total else 0.0,
        "severity_accuracy": round(correct_decisions / total, 4) if total else 0.0,
        "average_latency_seconds": round(mean(latencies), 4) if latencies else 0.0,
        "p95_latency_seconds": round(p95_latency, 4),
        "slo_latency_seconds": SLO_LATENCY_SECONDS,
        "p95_latency_slo_passed": p95_latency <= SLO_LATENCY_SECONDS,
        "data_source": str(INPUT_FILE) if INPUT_FILE.exists() else "deterministic_fallback_scenarios",
        "important_note": "This validates FlowPay decision behavior on 30-second event windows. It is not a portfolio return backtest.",
    }


def build_confusion_matrix(results: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    matrix: Dict[str, Dict[str, int]] = {}

    for r in results:
        expected = r["expected_severity"]
        actual = r["actual_severity"] or "NO_DECISION"

        matrix.setdefault(expected, {})
        matrix[expected].setdefault(actual, 0)
        matrix[expected][actual] += 1

    return matrix


def save_outputs(summary: Dict[str, Any], results: List[Dict[str, Any]]) -> None:
    confusion_matrix = build_confusion_matrix(results)

    evidence = {
        "summary": summary,
        "confusion_matrix": confusion_matrix,
        "results": results,
    }

    with open(OUTPUT_DIR / "flowpay_30s_event_replay_summary.json", "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)

    pd.DataFrame(results).to_csv(
        OUTPUT_DIR / "flowpay_30s_event_replay_results.csv",
        index=False,
    )

    readme = [
        "# FlowPay 30-Second Event Replay Validation",
        "",
        "## Purpose",
        "",
        "This test validates FlowPay against 30-second event windows, which matches the event-driven architecture.",
        "",
        "## What this validates",
        "",
        "- 30-second window processing",
        "- Data quality rejection",
        "- Decision output contract",
        "- Severity accuracy",
        "- MRS (Market Risk Score) validity",
        "- Action/severity alignment",
        "- Latency SLO (Service Level Objective)",
        "",
        "## What this does not validate",
        "",
        "- Real exchange order-book execution",
        "- True slippage/fill probability",
        "- Portfolio alpha",
        "- Investment performance",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(summary, indent=2),
        "```",
        "",
        "## Confusion Matrix",
        "",
        "```json",
        json.dumps(confusion_matrix, indent=2),
        "```",
    ]

    (OUTPUT_DIR / "flowpay_30s_event_replay_readme.md").write_text(
        "\n".join(readme),
        encoding="utf-8",
    )


def main() -> None:
    print("\nFLOWPAY 30-SECOND EVENT REPLAY VALIDATION")
    print("=" * 80)

    df = load_events()
    windows = split_into_30s_windows(df)

    results = []

    for window_name, window_df in windows.items():
        result = run_window_test(window_name, window_df)
        results.append(result)

        status = "PASS" if result["test_passed"] else "FAIL"
        print(
            f"{status} | {window_name} | "
            f"expected={result['expected_severity']} | "
            f"actual={result['actual_severity']} | "
            f"latency={result['latency_seconds']}s"
        )

    summary = summarize(results)
    save_outputs(summary, results)

    print("\nFINAL SUMMARY")
    print("=" * 80)
    print(json.dumps(summary, indent=2))

    print("\nSaved:")
    print(OUTPUT_DIR / "flowpay_30s_event_replay_summary.json")
    print(OUTPUT_DIR / "flowpay_30s_event_replay_results.csv")
    print(OUTPUT_DIR / "flowpay_30s_event_replay_readme.md")


if __name__ == "__main__":
    main()