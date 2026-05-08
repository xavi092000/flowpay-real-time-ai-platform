import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "data_quality"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

REQUIRED_FIELDS = {
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

VALID_SIDES = {"buy", "sell"}


# -----------------------------------------------------------------------------
# VALIDATION CORE
# -----------------------------------------------------------------------------
def validate_event(event: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors: List[str] = []

    # 1) Required fields
    missing = REQUIRED_FIELDS - set(event.keys())
    if missing:
        errors.append(f"missing_fields: {sorted(missing)}")

    # 2) Timestamp
    ts = pd.to_datetime(event.get("timestamp"), utc=True, errors="coerce")
    if pd.isna(ts):
        errors.append("invalid_timestamp")

    # 3) Side
    side = event.get("side")
    if side not in VALID_SIDES:
        errors.append(f"invalid_side: {side}")

    # 4) Numeric checks
    def is_valid_number(x):
        try:
            xf = float(x)
            return not (pd.isna(xf) or xf in (float("inf"), float("-inf")))
        except Exception:
            return False

    for field in ["price", "volume", "bid", "ask", "bid_depth", "ask_depth"]:
        if not is_valid_number(event.get(field)):
            errors.append(f"invalid_numeric_{field}")

    # 5) Range checks
    price = event.get("price")
    volume = event.get("volume")
    bid = event.get("bid")
    ask = event.get("ask")
    bid_depth = event.get("bid_depth")
    ask_depth = event.get("ask_depth")

    try:
        if float(price) <= 0:
            errors.append("price_must_be_positive")
    except Exception:
        pass

    try:
        if float(volume) <= 0:
            errors.append("volume_must_be_positive")
    except Exception:
        pass

    try:
        if float(bid) >= float(ask):
            errors.append("bid_must_be_lower_than_ask")
    except Exception:
        pass

    try:
        if float(bid_depth) <= 0 or float(ask_depth) <= 0:
            errors.append("depth_must_be_positive")
    except Exception:
        pass

    return len(errors) == 0, errors


# -----------------------------------------------------------------------------
# TEST SCENARIOS
# -----------------------------------------------------------------------------
def build_test_events() -> List[Dict[str, Any]]:
    return [
        # VALID
        {
            "scenario": "valid_normal",
            "event": {
                "event_id": "e1",
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
            "expected_valid": True,
        },
        # INVALID: missing price
        {
            "scenario": "missing_price",
            "event": {
                "event_id": "e2",
                "timestamp": "2026-04-28T10:00:00Z",
                "symbol": "BTC-USD",
                "side": "buy",
                "volume": 1.0,
                "bid": 66990,
                "ask": 67010,
                "bid_depth": 600000,
                "ask_depth": 610000,
            },
            "expected_valid": False,
        },
        # INVALID: negative volume
        {
            "scenario": "negative_volume",
            "event": {
                "event_id": "e3",
                "timestamp": "2026-04-28T10:00:00Z",
                "symbol": "BTC-USD",
                "side": "buy",
                "price": 67000,
                "volume": -1.0,
                "bid": 66990,
                "ask": 67010,
                "bid_depth": 600000,
                "ask_depth": 610000,
            },
            "expected_valid": False,
        },
        # INVALID: bid > ask
        {
            "scenario": "invalid_bid_ask",
            "event": {
                "event_id": "e4",
                "timestamp": "2026-04-28T10:00:00Z",
                "symbol": "BTC-USD",
                "side": "buy",
                "price": 67000,
                "volume": 1.0,
                "bid": 67010,
                "ask": 67000,
                "bid_depth": 600000,
                "ask_depth": 610000,
            },
            "expected_valid": False,
        },
        # EDGE: extreme but valid
        {
            "scenario": "extreme_valid",
            "event": {
                "event_id": "e5",
                "timestamp": "2026-04-28T10:00:00Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 1000000,
                "volume": 100,
                "bid": 999000,
                "ask": 1001000,
                "bid_depth": 10000,
                "ask_depth": 1000000,
            },
            "expected_valid": True,
        },
    ]


# -----------------------------------------------------------------------------
# RUNNER
# -----------------------------------------------------------------------------
def run_data_quality_validation() -> None:
    print("\nFLOWPAY DATA QUALITY VALIDATION")
    print("=" * 80)

    tests = build_test_events()
    results = []

    for t in tests:
        scenario = t["scenario"]
        event = t["event"]
        expected_valid = t["expected_valid"]

        actual_valid, errors = validate_event(event)

        test_passed = actual_valid == expected_valid

        result = {
            "scenario": scenario,
            "expected_valid": expected_valid,
            "actual_valid": actual_valid,
            "errors": errors,
            "test_passed": test_passed,
        }

        results.append(result)

        status = "PASS" if test_passed else "FAIL"
        print(f"{status} | {scenario} | errors={errors}")

    total = len(results)
    passed = sum(r["test_passed"] for r in results)

    summary = {
        "validation_type": "data_quality_layer",
        "total_tests": total,
        "passed_tests": passed,
        "failed_tests": total - passed,
        "pass_rate": round(passed / total, 4),
        "verdict": "PASS" if passed == total else "FAIL",
    }

    # Save
    with open(OUTPUT_DIR / "flowpay_data_quality_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    pd.DataFrame(results).to_csv(
        OUTPUT_DIR / "flowpay_data_quality_results.csv",
        index=False,
    )

    print("\nFINAL SUMMARY")
    print(json.dumps(summary, indent=2))

    print("\nSaved:")
    print(OUTPUT_DIR / "flowpay_data_quality_summary.json")
    print(OUTPUT_DIR / "flowpay_data_quality_results.csv")


if __name__ == "__main__":
    run_data_quality_validation()