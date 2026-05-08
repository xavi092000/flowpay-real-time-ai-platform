import json
from pathlib import Path
from typing import Any, Dict, List, Set

import pandas as pd

from flowpay_data_quality_layer import validate_event


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "failure_replay"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


MAX_RETRIES = 3


def build_replay_events() -> List[Dict[str, Any]]:
    return [
        {
            "scenario": "valid_event_processed_once",
            "event": {
                "event_id": "evt_001",
                "timestamp": "2026-04-28T10:00:00Z",
                "symbol": "BTC-USD",
                "side": "buy",
                "price": 67000,
                "volume": 1.0,
                "bid": 66990,
                "ask": 67010,
                "bid_depth": 600000,
                "ask_depth": 610000,
            },
            "expected_status": "PROCESSED",
        },
        {
            "scenario": "duplicate_event_id_skipped",
            "event": {
                "event_id": "evt_001",
                "timestamp": "2026-04-28T10:00:05Z",
                "symbol": "BTC-USD",
                "side": "buy",
                "price": 67005,
                "volume": 1.0,
                "bid": 66995,
                "ask": 67015,
                "bid_depth": 600000,
                "ask_depth": 610000,
            },
            "expected_status": "SKIPPED_DUPLICATE",
        },
        {
            "scenario": "invalid_event_sent_to_dlq",
            "event": {
                "event_id": "evt_002",
                "timestamp": "2026-04-28T10:00:10Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": -1,
                "volume": 1.0,
                "bid": 66990,
                "ask": 67010,
                "bid_depth": 600000,
                "ask_depth": 610000,
            },
            "expected_status": "DLQ",
        },
        {
            "scenario": "transient_failure_retried_then_processed",
            "event": {
                "event_id": "evt_003",
                "timestamp": "2026-04-28T10:00:15Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 66800,
                "volume": 2.0,
                "bid": 66790,
                "ask": 66810,
                "bid_depth": 500000,
                "ask_depth": 700000,
                "simulate_transient_failure": True,
            },
            "expected_status": "PROCESSED_AFTER_RETRY",
        },
    ]


def simulate_processing(event: Dict[str, Any], attempt: int) -> bool:
    if event.get("simulate_transient_failure") and attempt < 2:
        raise RuntimeError("Simulated transient processing failure")

    return True


def process_event(
    event: Dict[str, Any],
    processed_event_ids: Set[str],
) -> Dict[str, Any]:
    event_id = event.get("event_id", "UNKNOWN")

    if event_id in processed_event_ids:
        return {
            "event_id": event_id,
            "status": "SKIPPED_DUPLICATE",
            "attempts": 0,
            "errors": [],
            "idempotent": True,
        }

    valid, validation_errors = validate_event(event)

    if not valid:
        return {
            "event_id": event_id,
            "status": "DLQ",
            "attempts": 0,
            "errors": validation_errors,
            "idempotent": True,
        }

    errors = []

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            simulate_processing(event, attempt)
            processed_event_ids.add(event_id)

            status = "PROCESSED" if attempt == 1 else "PROCESSED_AFTER_RETRY"

            return {
                "event_id": event_id,
                "status": status,
                "attempts": attempt,
                "errors": errors,
                "idempotent": True,
            }

        except Exception as exc:
            errors.append(str(exc))

    return {
        "event_id": event_id,
        "status": "DLQ",
        "attempts": MAX_RETRIES,
        "errors": errors,
        "idempotent": True,
    }


def run_failure_replay_validation() -> None:
    print("\nFLOWPAY FAILURE REPLAY / RETRY / IDEMPOTENCY VALIDATION")
    print("=" * 80)

    processed_event_ids: Set[str] = set()
    test_cases = build_replay_events()
    results = []

    for test in test_cases:
        scenario = test["scenario"]
        expected_status = test["expected_status"]
        event = test["event"]

        outcome = process_event(event, processed_event_ids)

        test_passed = outcome["status"] == expected_status

        result = {
            "scenario": scenario,
            "expected_status": expected_status,
            "actual_status": outcome["status"],
            "attempts": outcome["attempts"],
            "errors": outcome["errors"],
            "idempotent": outcome["idempotent"],
            "test_passed": test_passed,
        }

        results.append(result)

        print(
            f"{'PASS' if test_passed else 'FAIL'} | "
            f"{scenario} | status={outcome['status']} | attempts={outcome['attempts']}"
        )

    total = len(results)
    passed = sum(1 for result in results if result["test_passed"])

    summary = {
        "validation_type": "failure_replay_retry_idempotency",
        "total_tests": total,
        "passed_tests": passed,
        "failed_tests": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "max_retries": MAX_RETRIES,
        "verdict": "PASS" if passed == total else "FAIL",
    }

    evidence = {
        "summary": summary,
        "results": results,
    }

    with open(OUTPUT_DIR / "flowpay_failure_replay_summary.json", "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)

    pd.DataFrame(results).to_csv(
        OUTPUT_DIR / "flowpay_failure_replay_results.csv",
        index=False,
    )

    print("\nFINAL SUMMARY")
    print(json.dumps(summary, indent=2))

    print("\nSaved:")
    print(OUTPUT_DIR / "flowpay_failure_replay_summary.json")
    print(OUTPUT_DIR / "flowpay_failure_replay_results.csv")


if __name__ == "__main__":
    run_failure_replay_validation()