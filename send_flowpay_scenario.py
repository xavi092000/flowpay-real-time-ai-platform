import json
import time
from datetime import datetime, timezone
from statistics import mean

import boto3

from flowpay_data_quality import validate_events


REGION = "us-east-1"
STATE_MACHINE_ARN = "arn:aws:states:us-east-1:201983196515:stateMachine:flowpay-decision-workflow"

sfn = boto3.client("stepfunctions", region_name=REGION)

MAX_WAIT_SECONDS = 120
POLL_INTERVAL_SECONDS = 0.5

SLO_LATENCY_SECONDS = 5.0
SLO_SUCCESS_RATE = 0.95


SCENARIOS = {
    "normal_market": {
        "expected_severity": "Normal",
        "events": [
            {
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
            {
                "event_id": "evt_002",
                "timestamp": "2026-04-28T10:00:15Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 67005,
                "volume": 1.0,
                "bid": 66995,
                "ask": 67015,
                "bid_depth": 602000,
                "ask_depth": 608000,
            },
        ],
    },

    "guarded_sell_pressure": {
        "expected_severity": "Guarded",
        "events": [
            {
                "event_id": "evt_003",
                "timestamp": "2026-04-28T10:01:00Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 66800,
                "volume": 3.0,
                "bid": 66780,
                "ask": 66840,
                "bid_depth": 500000,
                "ask_depth": 580000,
            },
            {
                "event_id": "evt_004",
                "timestamp": "2026-04-28T10:01:15Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 66650,
                "volume": 4.0,
                "bid": 66600,
                "ask": 66700,
                "bid_depth": 420000,
                "ask_depth": 560000,
            },
        ],
    },
}


def calculate_percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0

    sorted_values = sorted(values)
    index = int(round((percentile / 100) * (len(sorted_values) - 1)))
    return sorted_values[index]


def start_execution(payload: dict) -> str:
    unique_suffix = str(int(time.time() * 1000))
    name = f"{payload['run_id']}-{unique_suffix}".replace("_", "-")

    response = sfn.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        name=name,
        input=json.dumps(payload),
    )
    return response["executionArn"]


def wait_for_execution(execution_arn: str) -> dict:
    start_time = time.perf_counter()

    while True:
        elapsed_seconds = time.perf_counter() - start_time

        if elapsed_seconds > MAX_WAIT_SECONDS:
            return {
                "status": "TIMEOUT",
                "latency_seconds": round(elapsed_seconds, 4),
                "parsed_output": {},
            }

        response = sfn.describe_execution(executionArn=execution_arn)

        if response["status"] in {"SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"}:
            total_latency = time.perf_counter() - start_time
            output = response.get("output")

            if output:
                try:
                    response["parsed_output"] = json.loads(output)
                except json.JSONDecodeError:
                    response["parsed_output"] = {}
            else:
                response["parsed_output"] = {}

            response["latency_seconds"] = round(total_latency, 4)
            return response

        time.sleep(POLL_INTERVAL_SECONDS)


def main():
    print("\nFLOWPAY AUTOMATED SCENARIO TESTS (SLO + LATENCY VALIDATION)")
    print("=" * 80)

    results = []
    passed_count = 0
    latency_values = []

    for scenario_name, scenario in SCENARIOS.items():
        print(f"\nRunning scenario: {scenario_name}")

        dq_result = validate_events(scenario["events"])

        if not dq_result["passed"]:
            print("DATA QUALITY FAILED")

            results.append({
                "scenario": scenario_name,
                "expected_severity": scenario["expected_severity"],
                "actual_severity": None,
                "status": "FAILED_DATA_QUALITY",
                "latency_seconds": None,
                "slo_latency_passed": False,
                "test_passed": False,
                "quality_score": dq_result["quality_score"],
                "data_quality_errors": dq_result["invalid_event_details"],
            })
            continue

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        payload = {
            "run_id": f"{scenario_name}_{timestamp}",
            "scenario": scenario_name,
            "expected_severity": scenario["expected_severity"],
            "events": scenario["events"],
        }

        execution_arn = start_execution(payload)
        result = wait_for_execution(execution_arn)

        parsed_output = result.get("parsed_output", {})
        final_output = parsed_output.get("final_output", {})

        actual_severity = final_output.get("severity")
        mrs = final_output.get("mrs")
        action_bundle = final_output.get("action_bundle")
        latency_seconds = result.get("latency_seconds")

        if latency_seconds is not None:
            latency_values.append(latency_seconds)

        slo_latency_passed = (
            latency_seconds is not None
            and latency_seconds <= SLO_LATENCY_SECONDS
        )

        test_passed = (
            result["status"] == "SUCCEEDED"
            and actual_severity is not None
            and actual_severity == scenario["expected_severity"]
            and slo_latency_passed
        )

        if test_passed:
            passed_count += 1

        print(f"Expected: {scenario['expected_severity']}")
        print(f"Actual: {actual_severity}")
        print(f"Status: {result['status']}")
        print(f"MRS: {mrs}")
        print(f"Action Bundle: {action_bundle}")
        print(f"Latency Seconds: {latency_seconds}")
        print(f"SLO Latency Passed: {slo_latency_passed}")
        print(f"TEST RESULT: {'PASS' if test_passed else 'FAIL'}")

        results.append({
            "scenario": scenario_name,
            "expected_severity": scenario["expected_severity"],
            "actual_severity": actual_severity,
            "status": result["status"],
            "mrs": mrs,
            "action_bundle": action_bundle,
            "latency_seconds": latency_seconds,
            "slo_latency_target_seconds": SLO_LATENCY_SECONDS,
            "slo_latency_passed": slo_latency_passed,
            "quality_score": dq_result["quality_score"],
            "test_passed": test_passed,
        })

    total = len(results)
    success_rate = passed_count / total if total > 0 else 0.0

    p95_latency = calculate_percentile(latency_values, 95)
    avg_latency = mean(latency_values) if latency_values else 0.0

    slo_success_rate_passed = success_rate >= SLO_SUCCESS_RATE
    slo_p95_latency_passed = p95_latency <= SLO_LATENCY_SECONDS

    overall_slo_passed = slo_success_rate_passed and slo_p95_latency_passed

    summary = {
        "total_tests": total,
        "passed_tests": passed_count,
        "success_rate": round(success_rate, 4),
        "success_rate_target": SLO_SUCCESS_RATE,
        "success_rate_slo_passed": slo_success_rate_passed,
        "average_latency_seconds": round(avg_latency, 4),
        "p95_latency_seconds": round(p95_latency, 4),
        "p95_latency_target_seconds": SLO_LATENCY_SECONDS,
        "p95_latency_slo_passed": slo_p95_latency_passed,
        "overall_slo_passed": overall_slo_passed,
    }

    print("\nFINAL SUMMARY")
    print("=" * 80)
    print(f"Passed: {passed_count}/{total}")
    print(f"Success Rate: {success_rate:.2%}")
    print(f"Average Latency: {avg_latency:.4f}s")
    print(f"P95 Latency: {p95_latency:.4f}s")
    print(f"SLO Success Rate Passed: {slo_success_rate_passed}")
    print(f"SLO P95 Latency Passed: {slo_p95_latency_passed}")
    print(f"OVERALL SLO PASSED: {overall_slo_passed}")

    with open("flowpay_slo_results.json", "w", encoding="utf-8") as f:
        json.dump({
            "summary": summary,
            "results": results,
        }, f, indent=2)

    print("\nSaved: flowpay_slo_results.json")


if __name__ == "__main__":
    main()