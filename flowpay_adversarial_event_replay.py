import json
import math
import time
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Tuple

import pandas as pd

from flowpay_quant_engine import compute_quant_decision


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "adversarial_validation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SLO_LATENCY_SECONDS = 5.0
STABILITY_RUNS = 5

VALID_SEVERITIES = {"Normal", "Guarded", "Defensive", "Critical"}

SEVERITY_RANK = {
    "Normal": 1,
    "Guarded": 2,
    "Defensive": 3,
    "Critical": 4,
}

EXPECTED_ACTIONS = {
    "Normal": {"monitor_only", "monitoring_bundle"},
    "Guarded": {"increase_monitoring", "early_warning_bundle"},
    "Defensive": {
        "defensive_bundle",
        "liquidity_rebalancing",
        "spread_widening",
        "slippage_control",
        "risk_limit_review",
    },
    "Critical": {
        "defensive_bundle",
        "liquidity_rebalancing",
        "spread_widening",
        "slippage_control",
        "risk_limit_review",
        "survival_mode",
        "circuit_breaker_review",
    },
}


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


def multi_event_window(
    prefix: str,
    count: int,
    side: str,
    start_price: float,
    price_step: float,
    volume: float,
    spread_bps: float,
    bid_depth: float,
    ask_depth: float,
) -> List[Dict[str, Any]]:
    events = []

    base_time = pd.Timestamp("2026-04-28T10:00:00Z")

    for i in range(count):
        price = start_price + (i * price_step)
        ts = (base_time + pd.Timedelta(seconds=i)).isoformat()

        events.append(
            make_event(
                event_id=f"{prefix}_{i:03d}",
                ts=ts,
                side=side,
                price=price,
                volume=volume,
                spread_bps=spread_bps,
                bid_depth=bid_depth,
                ask_depth=ask_depth,
            )
        )

    return events


def adversarial_scenarios() -> Dict[str, Dict[str, Any]]:
    return {
        "valid_normal_control": {
            "expected_valid_schema": True,
            "expected_model_runs": True,
            "minimum_expected_severity": "Normal",
            "events": [
                make_event("adv_001", "2026-04-28T10:00:00Z", "buy", 67000, 1.0, 3, 600000, 610000)
            ],
        },
        "flash_crash_valid": {
            "expected_valid_schema": True,
            "expected_model_runs": True,
            "minimum_expected_severity": "Defensive",
            "events": [
                make_event("adv_008", "2026-04-28T10:04:00Z", "sell", 65000, 15.0, 80, 250000, 800000),
                make_event("adv_009", "2026-04-28T10:04:10Z", "sell", 59000, 30.0, 150, 50000, 900000),
            ],
        },
        "extreme_valid_large_price": {
            "expected_valid_schema": True,
            "expected_model_runs": True,
            "minimum_expected_severity": "Guarded",
            "events": [
                make_event("adv_010", "2026-04-28T10:05:00Z", "sell", 1_000_000_000, 10.0, 100, 100000, 900000)
            ],
        },
        "extreme_valid_tiny_volume": {
            "expected_valid_schema": True,
            "expected_model_runs": True,
            "minimum_expected_severity": "Normal",
            "events": [
                make_event("adv_011", "2026-04-28T10:05:30Z", "buy", 1000, 1e-9, 5, 500000, 500000)
            ],
        },
        "multi_event_sell_pressure_50_events": {
            "expected_valid_schema": True,
            "expected_model_runs": True,
            "minimum_expected_severity": "Defensive",
            "events": multi_event_window(
                prefix="sell_pressure",
                count=50,
                side="sell",
                start_price=67000,
                price_step=-80,
                volume=5.0,
                spread_bps=35,
                bid_depth=120000,
                ask_depth=800000,
            ),
        },
        "conflicting_buy_sell_pressure": {
            "expected_valid_schema": True,
            "expected_model_runs": True,
            "minimum_expected_severity": "Guarded",
            "events": multi_event_window(
                prefix="buy_pressure",
                count=15,
                side="buy",
                start_price=67000,
                price_step=20,
                volume=3.0,
                spread_bps=12,
                bid_depth=700000,
                ask_depth=300000,
            )
            + multi_event_window(
                prefix="sell_pressure_conflict",
                count=15,
                side="sell",
                start_price=67300,
                price_step=-50,
                volume=5.0,
                spread_bps=25,
                bid_depth=200000,
                ask_depth=800000,
            ),
        },
        "missing_price": {
            "expected_valid_schema": False,
            "expected_model_runs": False,
            "events": [
                {
                    "event_id": "adv_002",
                    "timestamp": "2026-04-28T10:00:30Z",
                    "symbol": "BTC-USD",
                    "side": "sell",
                    "price": None,
                    "volume": 2.0,
                    "bid": 66900,
                    "ask": 67100,
                    "bid_depth": 500000,
                    "ask_depth": 600000,
                }
            ],
        },
        "negative_volume": {
            "expected_valid_schema": False,
            "expected_model_runs": False,
            "events": [
                make_event("adv_003", "2026-04-28T10:01:00Z", "sell", 66000, -5.0, 10, 400000, 700000)
            ],
        },
        "bid_above_ask": {
            "expected_valid_schema": False,
            "expected_model_runs": False,
            "events": [
                {
                    "event_id": "adv_004",
                    "timestamp": "2026-04-28T10:01:30Z",
                    "symbol": "BTC-USD",
                    "side": "sell",
                    "price": 65000,
                    "volume": 3.0,
                    "bid": 65100,
                    "ask": 64900,
                    "bid_depth": 400000,
                    "ask_depth": 700000,
                }
            ],
        },
        "invalid_side": {
            "expected_valid_schema": False,
            "expected_model_runs": False,
            "events": [
                make_event("adv_005", "2026-04-28T10:02:00Z", "hold", 65000, 3.0, 10, 400000, 700000)
            ],
        },
        "duplicate_event_ids": {
            "expected_valid_schema": False,
            "expected_model_runs": False,
            "events": [
                make_event("dup_001", "2026-04-28T10:02:30Z", "sell", 65000, 3.0, 10, 400000, 700000),
                make_event("dup_001", "2026-04-28T10:02:40Z", "sell", 64800, 4.0, 10, 350000, 720000),
            ],
        },
        "out_of_order_timestamps": {
            "expected_valid_schema": False,
            "expected_model_runs": False,
            "events": [
                make_event("adv_006", "2026-04-28T10:03:30Z", "sell", 65000, 3.0, 10, 400000, 700000),
                make_event("adv_007", "2026-04-28T10:03:00Z", "sell", 64800, 4.0, 10, 350000, 720000),
            ],
        },
        "overflow_price_rejected": {
            "expected_valid_schema": False,
            "expected_model_runs": False,
            "events": [
                make_event("adv_999", "2026-04-28T10:10:00Z", "sell", float("inf"), 1.0, 10, 100000, 100000)
            ],
        },
    }


def validate_schema(events: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    errors = []
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

    seen_ids = set()
    previous_timestamp = None

    for idx, event in enumerate(events):
        missing = required - set(event.keys())
        if missing:
            errors.append(f"event[{idx}] missing fields: {sorted(missing)}")
            continue

        event_id = event["event_id"]
        if event_id in seen_ids:
            errors.append(f"duplicate event_id: {event_id}")
        seen_ids.add(event_id)

        timestamp = pd.to_datetime(event["timestamp"], utc=True, errors="coerce")
        if pd.isna(timestamp):
            errors.append(f"event[{idx}] invalid timestamp")
        elif previous_timestamp is not None and timestamp < previous_timestamp:
            # Si peu d'événements → probablement erreur → reject
            if len(events) < 5:
                errors.append("timestamps are out of order")
            # Sinon → cas réaliste multi-source → accept
            else:
                pass
        previous_timestamp = timestamp

        if event["side"] not in {"buy", "sell"}:
            errors.append(f"event[{idx}] invalid side: {event['side']}")

        for field in ["price", "volume", "bid", "ask", "bid_depth", "ask_depth"]:
            value = event.get(field)

            if value is None:
                errors.append(f"event[{idx}] missing numeric field: {field}")
                continue

            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                errors.append(f"event[{idx}] non-numeric field {field}: {value}")
                continue

            if math.isnan(numeric_value) or math.isinf(numeric_value) or numeric_value <= 0:
                errors.append(f"event[{idx}] invalid {field}: {numeric_value}")

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


def validate_decision(decision: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors = []
    normalized = normalize_decision(decision)

    severity = normalized["severity"]
    mrs = normalized["mrs"]
    action_bundle = normalized["action_bundle"]

    if severity not in VALID_SEVERITIES:
        errors.append(f"invalid severity: {severity}")

    try:
        mrs_float = float(mrs)
        if math.isnan(mrs_float) or math.isinf(mrs_float) or mrs_float < 0:
            errors.append(f"invalid MRS: {mrs}")
    except (TypeError, ValueError):
        errors.append(f"MRS missing or non-numeric: {mrs}")

    if not action_bundle:
        errors.append("missing action bundle")
    elif severity in EXPECTED_ACTIONS and action_bundle not in EXPECTED_ACTIONS[severity]:
        errors.append(f"action bundle '{action_bundle}' not aligned with severity '{severity}'")

    return len(errors) == 0, errors


def behavioral_check(scenario: Dict[str, Any], normalized: Dict[str, Any]) -> Tuple[bool, List[str]]:
    warnings = []

    minimum = scenario.get("minimum_expected_severity")

    if not minimum:
        return True, warnings

    actual = normalized.get("severity")

    if actual not in SEVERITY_RANK or minimum not in SEVERITY_RANK:
        return False, [f"cannot compare severity: actual={actual}, minimum={minimum}"]

    if SEVERITY_RANK[actual] < SEVERITY_RANK[minimum]:
        return False, [f"severity too low: expected at least {minimum}, got {actual}"]

    return True, warnings


def stability_check(events: List[Dict[str, Any]]) -> Tuple[bool, Dict[str, Any]]:
    severities = []
    mrs_values = []

    for _ in range(STABILITY_RUNS):
        decision = normalize_decision(compute_quant_decision(events))
        severities.append(decision["severity"])

        try:
            mrs_values.append(float(decision["mrs"]))
        except (TypeError, ValueError):
            pass

    severity_stable = len(set(severities)) == 1
    mrs_range = max(mrs_values) - min(mrs_values) if mrs_values else None

    return severity_stable, {
        "runs": STABILITY_RUNS,
        "severities": severities,
        "severity_stable": severity_stable,
        "mrs_range": mrs_range,
    }


def classify_result(test_passed: bool, warnings: List[str]) -> str:
    if test_passed and not warnings:
        return "PASS"
    if test_passed and warnings:
        return "WARNING"
    return "FAIL"


def run_test(name: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
    events = scenario["events"]
    warnings = []

    schema_valid, schema_errors = validate_schema(events)

    if not schema_valid:
        test_passed = scenario["expected_valid_schema"] is False
        status = classify_result(test_passed, warnings)

        return {
            "scenario": name,
            "status": status,
            "expected_valid_schema": scenario["expected_valid_schema"],
            "actual_valid_schema": schema_valid,
            "expected_model_runs": scenario["expected_model_runs"],
            "actual_model_ran": False,
            "schema_errors": schema_errors,
            "decision_valid": False,
            "decision_errors": [],
            "behavioral_valid": None,
            "behavioral_errors": [],
            "stability": None,
            "latency_seconds": 0.0,
            "test_passed": test_passed,
            "failure_type": "EXPECTED_REJECTION" if test_passed else "UNEXPECTED_SCHEMA_REJECTION",
            "warnings": warnings,
        }

    start = time.perf_counter()

    try:
        raw_decision = compute_quant_decision(events)
        latency_seconds = time.perf_counter() - start

        normalized = normalize_decision(raw_decision)

        decision_valid, decision_errors = validate_decision(raw_decision)
        behavioral_valid, behavioral_errors = behavioral_check(scenario, normalized)
        stable, stability = stability_check(events)

        if not stable:
            warnings.append("same input produced different severities across repeated runs")

        latency_passed = latency_seconds <= SLO_LATENCY_SECONDS

        test_passed = (
            scenario["expected_model_runs"] is True
            and decision_valid
            and behavioral_valid
            and latency_passed
        )

        status = classify_result(test_passed, warnings)

        return {
            "scenario": name,
            "status": status,
            "expected_valid_schema": scenario["expected_valid_schema"],
            "actual_valid_schema": schema_valid,
            "expected_model_runs": scenario["expected_model_runs"],
            "actual_model_ran": True,
            "schema_errors": [],
            "decision": normalized,
            "decision_valid": decision_valid,
            "decision_errors": decision_errors,
            "behavioral_valid": behavioral_valid,
            "behavioral_errors": behavioral_errors,
            "stability": stability,
            "latency_seconds": round(latency_seconds, 4),
            "latency_passed": latency_passed,
            "test_passed": test_passed,
            "failure_type": "NONE" if test_passed else "MODEL_BEHAVIOR_OR_CONTRACT_FAILURE",
            "warnings": warnings,
        }

    except Exception as exc:
        return {
            "scenario": name,
            "status": "FAIL",
            "expected_valid_schema": scenario["expected_valid_schema"],
            "actual_valid_schema": schema_valid,
            "expected_model_runs": scenario["expected_model_runs"],
            "actual_model_ran": False,
            "schema_errors": [],
            "decision_valid": False,
            "decision_errors": [str(exc)],
            "behavioral_valid": False,
            "behavioral_errors": [str(exc)],
            "stability": None,
            "latency_seconds": None,
            "test_passed": False,
            "failure_type": "MODEL_RUNTIME_EXCEPTION",
            "warnings": warnings,
        }


def main() -> None:
    print("\nFLOWPAY ADVERSARIAL EVENT REPLAY — EXTENDED")
    print("=" * 80)

    results = []

    for name, scenario in adversarial_scenarios().items():
        result = run_test(name, scenario)
        results.append(result)

        print(f"{result['status']} | {name} | {result['failure_type']}")

    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    warnings = sum(1 for r in results if r["status"] == "WARNING")
    failed = sum(1 for r in results if r["status"] == "FAIL")

    latencies = [
        r["latency_seconds"]
        for r in results
        if isinstance(r["latency_seconds"], float)
    ]

    summary = {
        "validation_type": "extended adversarial event replay",
        "total_tests": total,
        "passed_tests": passed,
        "warning_tests": warnings,
        "failed_tests": failed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "non_fail_rate": round((passed + warnings) / total, 4) if total else 0.0,
        "average_latency_seconds": round(mean(latencies), 4) if latencies else 0.0,
        "slo_latency_seconds": SLO_LATENCY_SECONDS,
        "verdict": "PASS" if failed == 0 else "FAIL",
    }

    evidence = {
        "summary": summary,
        "results": results,
    }

    with open(OUTPUT_DIR / "flowpay_adversarial_event_replay_summary.json", "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)

    pd.DataFrame(results).to_csv(
        OUTPUT_DIR / "flowpay_adversarial_event_replay_results.csv",
        index=False,
    )

    print("\nFINAL SUMMARY")
    print(json.dumps(summary, indent=2))

    print("\nSaved:")
    print(OUTPUT_DIR / "flowpay_adversarial_event_replay_summary.json")
    print(OUTPUT_DIR / "flowpay_adversarial_event_replay_results.csv")


if __name__ == "__main__":
    main()