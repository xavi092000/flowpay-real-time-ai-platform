import json
import time
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List

import pandas as pd

from flowpay_quant_engine import compute_quant_decision


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "event_replay_30s"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SLO_LATENCY_SECONDS = 5.0
WINDOW_SECONDS = 30

VALID_SEVERITIES = {"Normal", "Guarded", "Defensive", "Critical"}


def make_event(
    event_id: str,
    ts: str,
    side: str,
    price: float,
    volume: float,
    spread_bps: float,
    bid_depth: float,
    ask_depth: float,
    symbol: str = "BTC-USD",
) -> Dict[str, Any]:
    spread = price * spread_bps / 10_000

    return {
        "event_id": event_id,
        "timestamp": ts,
        "symbol": symbol,
        "side": side,
        "price": price,
        "volume": volume,
        "bid": price - spread,
        "ask": price + spread,
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
    }


def scenario_windows() -> Dict[str, Dict[str, Any]]:
    return {
        "normal_market_30s": {
            "minimum_expected_severity": "Normal",
            "events": [
                make_event("n1", "2026-04-28T10:00:00Z", "buy", 67000, 1.0, 3, 600000, 610000),
                make_event("n2", "2026-04-28T10:00:10Z", "buy", 67010, 0.8, 3, 605000, 608000),
                make_event("n3", "2026-04-28T10:00:20Z", "sell", 67005, 0.7, 3, 602000, 609000),
            ],
        },
        "guarded_sell_pressure_30s": {
            "minimum_expected_severity": "Guarded",
            "events": [
                make_event("g1", "2026-04-28T10:01:00Z", "sell", 67000, 3.0, 10, 450000, 700000),
                make_event("g2", "2026-04-28T10:01:10Z", "sell", 66850, 4.0, 15, 350000, 760000),
                make_event("g3", "2026-04-28T10:01:20Z", "buy", 66900, 1.0, 12, 370000, 740000),
            ],
        },
        "defensive_liquidity_stress_30s": {
            "minimum_expected_severity": "Defensive",
            "events": [
                make_event("d1", "2026-04-28T10:02:00Z", "sell", 67000, 5.0, 25, 300000, 700000),
                make_event("d2", "2026-04-28T10:02:10Z", "sell", 66500, 7.0, 35, 120000, 820000),
                make_event("d3", "2026-04-28T10:02:20Z", "sell", 66200, 8.0, 45, 70000, 900000),
            ],
        },
        "critical_flash_crash_30s": {
            "minimum_expected_severity": "Critical",
            "events": [
                make_event("c1", "2026-04-28T10:03:00Z", "sell", 65000, 15.0, 80, 250000, 800000),
                make_event("c2", "2026-04-28T10:03:10Z", "sell", 61500, 25.0, 120, 100000, 880000),
                make_event("c3", "2026-04-28T10:03:20Z", "sell", 59000, 30.0, 150, 50000, 900000),
            ],
        },
    }


def normalize_decision(decision: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "mrs": decision.get("mrs", decision.get("market_risk_score")),
        "severity": decision.get("severity"),
        "action_bundle": decision.get("action_bundle", decision.get("recommended_action")),
    }


def severity_rank(severity: str) -> int:
    return {
        "Normal": 1,
        "Guarded": 2,
        "Defensive": 3,
        "Critical": 4,
    }.get(severity, 0)


def validate_window_span(events: List[Dict[str, Any]]) -> bool:
    timestamps = [
        pd.to_datetime(event["timestamp"], utc=True, errors="coerce")
        for event in events
    ]

    if any(pd.isna(ts) for ts in timestamps):
        return False

    span_seconds = (max(timestamps) - min(timestamps)).total_seconds()
    return span_seconds <= WINDOW_SECONDS


def validate_decision(
    normalized: Dict[str, Any],
    minimum_expected_severity: str,
) -> tuple[bool, List[str]]:
    errors = []

    severity = normalized.get("severity")
    mrs = normalized.get("mrs")
    action_bundle = normalized.get("action_bundle")

    if severity not in VALID_SEVERITIES:
        errors.append(f"invalid severity: {severity}")

    try:
        mrs_float = float(mrs)
        if mrs_float < 0:
            errors.append(f"invalid MRS: {mrs}")
    except (TypeError, ValueError):
        errors.append(f"MRS missing or non-numeric: {mrs}")

    if not action_bundle:
        errors.append("missing action_bundle")

    if severity_rank(severity) < severity_rank(minimum_expected_severity):
        errors.append(
            f"severity too low: expected at least {minimum_expected_severity}, got {severity}"
        )

    return len(errors) == 0, errors


def run_validation() -> None:
    print("\nFLOWPAY 30S EVENT REPLAY VALIDATION")
    print("=" * 80)

    results = []

    for name, scenario in scenario_windows().items():
        events = scenario["events"]
        window_valid = validate_window_span(events)

        start = time.perf_counter()
        decision = compute_quant_decision(events)
        latency_seconds = time.perf_counter() - start

        normalized = normalize_decision(decision)

        decision_valid, decision_errors = validate_decision(
            normalized=normalized,
            minimum_expected_severity=scenario["minimum_expected_severity"],
        )

        latency_passed = latency_seconds <= SLO_LATENCY_SECONDS

        test_passed = window_valid and decision_valid and latency_passed

        result = {
            "scenario": name,
            "status": "PASS" if test_passed else "FAIL",
            "window_seconds_target": WINDOW_SECONDS,
            "window_valid": window_valid,
            "minimum_expected_severity": scenario["minimum_expected_severity"],
            "decision": normalized,
            "decision_valid": decision_valid,
            "decision_errors": decision_errors,
            "latency_seconds": round(latency_seconds, 4),
            "slo_latency_seconds": SLO_LATENCY_SECONDS,
            "latency_passed": latency_passed,
            "test_passed": test_passed,
        }

        results.append(result)

        print(
            f"{result['status']} | {name} | "
            f"severity={normalized['severity']} | "
            f"mrs={normalized['mrs']} | "
            f"latency={result['latency_seconds']}s"
        )

    total = len(results)
    passed = sum(1 for result in results if result["status"] == "PASS")
    failed = total - passed

    latencies = [result["latency_seconds"] for result in results]

    summary = {
        "validation_type": "30-second event replay validation",
        "window_seconds": WINDOW_SECONDS,
        "total_tests": total,
        "passed_tests": passed,
        "failed_tests": failed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "average_latency_seconds": round(mean(latencies), 4) if latencies else 0.0,
        "max_latency_seconds": round(max(latencies), 4) if latencies else 0.0,
        "slo_latency_seconds": SLO_LATENCY_SECONDS,
        "verdict": "PASS" if failed == 0 else "FAIL",
    }

    evidence = {
        "summary": summary,
        "results": results,
    }

    with open(OUTPUT_DIR / "flowpay_30s_event_replay_summary.json", "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)

    pd.DataFrame(results).to_csv(
        OUTPUT_DIR / "flowpay_30s_event_replay_results.csv",
        index=False,
    )

    print("\nFINAL SUMMARY")
    print(json.dumps(summary, indent=2))

    print("\nSaved:")
    print(OUTPUT_DIR / "flowpay_30s_event_replay_summary.json")
    print(OUTPUT_DIR / "flowpay_30s_event_replay_results.csv")


if __name__ == "__main__":
    run_validation()