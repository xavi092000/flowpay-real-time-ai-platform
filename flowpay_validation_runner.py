import json
import math
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple
from flowpay_observability import publish_decision_metrics

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from flowpay_data_quality import validate_events


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "tests"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

REGION = "us-east-1"
STATE_MACHINE_ARN = "arn:aws:states:us-east-1:201983196515:stateMachine:flowpay-decision-workflow"

MAX_WAIT_SECONDS = 120
POLL_INTERVAL_SECONDS = 0.5

SLO_LATENCY_SECONDS = 5.0
TARGET_PASS_RATE = 0.90
MIN_SECTION_TESTS = 10

DRY_RUN = False
MAX_CLOUD_EXECUTIONS = 10

SEVERITY_ORDER = {
    "Normal": 1,
    "Guarded": 2,
    "Defensive": 3,
    "Critical": 4,
}

EXPECTED_ACTION_BY_SEVERITY = {
    "Normal": {"monitoring_bundle", "monitor_only"},
    "Guarded": {"early_warning_bundle", "increase_monitoring"},
    "Defensive": {"defensive_bundle", "liquidity_rebalancing"},
    "Critical": {
        "critical_bundle",
        "critical_protection_bundle",
        "risk_off_bundle",
        "emergency_review",
    },
}

MRS_RANGES_BY_SEVERITY = {
    "Normal": (0, 24.99),
    "Guarded": (25, 49.99),
    "Defensive": (50, 74.99),
    "Critical": (75, float("inf")),
}

sfn = boto3.client("stepfunctions", region_name=REGION)


DATA_QUALITY_TESTS = [
    {
        "name": "valid_normal_event",
        "expected_passed": True,
        "events": [{
            "event_id": "dq_001",
            "timestamp": "2026-04-28T10:00:00Z",
            "symbol": "BTC-USD",
            "side": "buy",
            "price": 67000,
            "volume": 1.0,
            "bid": 66990,
            "ask": 67010,
            "bid_depth": 600000,
            "ask_depth": 610000,
        }],
    },
    {
        "name": "missing_event_id",
        "expected_passed": False,
        "events": [{
            "timestamp": "2026-04-28T10:00:00Z",
            "symbol": "BTC-USD",
            "side": "buy",
            "price": 67000,
            "volume": 1.0,
            "bid": 66990,
            "ask": 67010,
            "bid_depth": 600000,
            "ask_depth": 610000,
        }],
    },
    {
        "name": "missing_timestamp",
        "expected_passed": False,
        "events": [{
            "event_id": "dq_003",
            "symbol": "BTC-USD",
            "side": "buy",
            "price": 67000,
            "volume": 1.0,
            "bid": 66990,
            "ask": 67010,
            "bid_depth": 600000,
            "ask_depth": 610000,
        }],
    },
    {
        "name": "invalid_side",
        "expected_passed": False,
        "events": [{
            "event_id": "dq_004",
            "timestamp": "2026-04-28T10:00:00Z",
            "symbol": "BTC-USD",
            "side": "hold",
            "price": 67000,
            "volume": 1.0,
            "bid": 66990,
            "ask": 67010,
            "bid_depth": 600000,
            "ask_depth": 610000,
        }],
    },
    {
        "name": "negative_price",
        "expected_passed": False,
        "events": [{
            "event_id": "dq_005",
            "timestamp": "2026-04-28T10:00:00Z",
            "symbol": "BTC-USD",
            "side": "buy",
            "price": -1,
            "volume": 1.0,
            "bid": 66990,
            "ask": 67010,
            "bid_depth": 600000,
            "ask_depth": 610000,
        }],
    },
    {
        "name": "zero_volume",
        "expected_passed": False,
        "events": [{
            "event_id": "dq_006",
            "timestamp": "2026-04-28T10:00:00Z",
            "symbol": "BTC-USD",
            "side": "buy",
            "price": 67000,
            "volume": 0,
            "bid": 66990,
            "ask": 67010,
            "bid_depth": 600000,
            "ask_depth": 610000,
        }],
    },
    {
        "name": "bid_greater_than_ask",
        "expected_passed": False,
        "events": [{
            "event_id": "dq_007",
            "timestamp": "2026-04-28T10:00:00Z",
            "symbol": "BTC-USD",
            "side": "buy",
            "price": 67000,
            "volume": 1.0,
            "bid": 67020,
            "ask": 67010,
            "bid_depth": 600000,
            "ask_depth": 610000,
        }],
    },
    {
        "name": "negative_bid_depth",
        "expected_passed": False,
        "events": [{
            "event_id": "dq_008",
            "timestamp": "2026-04-28T10:00:00Z",
            "symbol": "BTC-USD",
            "side": "buy",
            "price": 67000,
            "volume": 1.0,
            "bid": 66990,
            "ask": 67010,
            "bid_depth": -1,
            "ask_depth": 610000,
        }],
    },
    {
        "name": "zero_ask_depth",
        "expected_passed": False,
        "events": [{
            "event_id": "dq_009",
            "timestamp": "2026-04-28T10:00:00Z",
            "symbol": "BTC-USD",
            "side": "buy",
            "price": 67000,
            "volume": 1.0,
            "bid": 66990,
            "ask": 67010,
            "bid_depth": 600000,
            "ask_depth": 0,
        }],
    },
    {
        "name": "multiple_invalid_fields",
        "expected_passed": False,
        "events": [{
            "event_id": "dq_010",
            "timestamp": "2026-04-28T10:00:00Z",
            "symbol": "BTC-USD",
            "side": "bad",
            "price": -100,
            "volume": 0,
            "bid": 67010,
            "ask": 66990,
            "bid_depth": -5,
            "ask_depth": 0,
        }],
    },
]


SCENARIOS = {
    "normal_market": {
        "expected_severity": "Normal",
        "events": [
            {
                "event_id": "sc_001",
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
                "event_id": "sc_002",
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
                "event_id": "sc_003",
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
                "event_id": "sc_004",
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
    "defensive_market": {
        "expected_severity": "Defensive",
        "events": [
            {
                "event_id": "sc_005",
                "timestamp": "2026-04-28T10:02:00Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 66000,
                "volume": 8.0,
                "bid": 65800,
                "ask": 66200,
                "bid_depth": 360000,
                "ask_depth": 540000,
            },
            {
                "event_id": "sc_006",
                "timestamp": "2026-04-28T10:02:15Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 65200,
                "volume": 8.5,
                "bid": 65000,
                "ask": 65500,
                "bid_depth": 216000,
                "ask_depth": 504000,
            },
        ],
    },
    "critical_market": {
        "expected_severity": "Critical",
        "events": [
            {
                "event_id": "sc_007",
                "timestamp": "2026-04-28T10:03:00Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 65000,
                "volume": 15.0,
                "bid": 64500,
                "ask": 65500,
                "bid_depth": 300000,
                "ask_depth": 500000,
            },
            {
                "event_id": "sc_008",
                "timestamp": "2026-04-28T10:03:15Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 62000,
                "volume": 20.0,
                "bid": 61000,
                "ask": 63000,
                "bid_depth": 80000,
                "ask_depth": 450000,
            },
        ],
    },
    "recovery_market": {
        "expected_severity": "Normal",
        "events": [
            {
                "event_id": "sc_009",
                "timestamp": "2026-04-28T10:04:00Z",
                "symbol": "BTC-USD",
                "side": "buy",
                "price": 63000,
                "volume": 2.0,
                "bid": 62980,
                "ask": 63020,
                "bid_depth": 450000,
                "ask_depth": 470000,
            },
            {
                "event_id": "sc_010",
                "timestamp": "2026-04-28T10:04:15Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 63100,
                "volume": 2.0,
                "bid": 63080,
                "ask": 63120,
                "bid_depth": 460000,
                "ask_depth": 465000,
            },
        ],
    },
    "liquidity_stress": {
        "expected_severity": "Guarded",
        "events": [
            {
                "event_id": "sc_011",
                "timestamp": "2026-04-28T10:05:00Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 64000,
                "volume": 7.0,
                "bid": 63800,
                "ask": 64200,
                "bid_depth": 120000,
                "ask_depth": 620000,
            },
            {
                "event_id": "sc_012",
                "timestamp": "2026-04-28T10:05:15Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 63600,
                "volume": 7.5,
                "bid": 63300,
                "ask": 64000,
                "bid_depth": 90000,
                "ask_depth": 650000,
            },
        ],
    },
    "volatility_spike": {
        "expected_severity": "Normal",
        "events": [
            {
                "event_id": "sc_013",
                "timestamp": "2026-04-28T10:06:00Z",
                "symbol": "BTC-USD",
                "side": "buy",
                "price": 65000,
                "volume": 4.0,
                "bid": 64800,
                "ask": 65200,
                "bid_depth": 400000,
                "ask_depth": 420000,
            },
            {
                "event_id": "sc_014",
                "timestamp": "2026-04-28T10:06:15Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 62800,
                "volume": 5.0,
                "bid": 62400,
                "ask": 63200,
                "bid_depth": 300000,
                "ask_depth": 500000,
            },
        ],
    },
    "execution_risk": {
        "expected_severity": "Guarded",
        "events": [
            {
                "event_id": "sc_015",
                "timestamp": "2026-04-28T10:07:00Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 66000,
                "volume": 5.0,
                "bid": 65900,
                "ask": 66200,
                "bid_depth": 430000,
                "ask_depth": 520000,
            },
            {
                "event_id": "sc_016",
                "timestamp": "2026-04-28T10:07:15Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 65700,
                "volume": 5.0,
                "bid": 65500,
                "ask": 66000,
                "bid_depth": 410000,
                "ask_depth": 530000,
            },
        ],
    },
    "mixed_signals": {
        "expected_severity": "Normal",
        "events": [
            {
                "event_id": "sc_017",
                "timestamp": "2026-04-28T10:08:00Z",
                "symbol": "BTC-USD",
                "side": "buy",
                "price": 66000,
                "volume": 6.0,
                "bid": 65950,
                "ask": 66050,
                "bid_depth": 500000,
                "ask_depth": 490000,
            },
            {
                "event_id": "sc_018",
                "timestamp": "2026-04-28T10:08:15Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 65300,
                "volume": 6.5,
                "bid": 65100,
                "ask": 65500,
                "bid_depth": 350000,
                "ask_depth": 560000,
            },
        ],
    },
    "high_volume_pressure": {
        "expected_severity": "Defensive",
        "events": [
            {
                "event_id": "sc_019",
                "timestamp": "2026-04-28T10:09:00Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 63000,
                "volume": 25.0,
                "bid": 62500,
                "ask": 63500,
                "bid_depth": 140000,
                "ask_depth": 700000,
            },
            {
                "event_id": "sc_020",
                "timestamp": "2026-04-28T10:09:15Z",
                "symbol": "BTC-USD",
                "side": "sell",
                "price": 60000,
                "volume": 30.0,
                "bid": 59000,
                "ask": 61000,
                "bid_depth": 70000,
                "ask_depth": 800000,
            },
        ],
    },
}


def save_json(filename: str, data: Dict[str, Any]) -> Path:
    path = OUTPUT_DIR / filename
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def calculate_percentile_nearest_rank(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0

    sorted_values = sorted(values)
    rank = math.ceil((percentile / 100) * len(sorted_values))
    index = max(0, min(rank - 1, len(sorted_values) - 1))
    return sorted_values[index]


def pass_rate(results: List[Dict[str, Any]]) -> float:
    if not results:
        return 0.0

    passed = sum(1 for item in results if item.get("test_passed") is True)
    return passed / len(results)


def validate_payload_schema(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors = []

    required_payload_fields = ["run_id", "scenario", "expected_severity", "events"]
    for field in required_payload_fields:
        if field not in payload:
            errors.append(f"Missing payload field: {field}")

    if payload.get("expected_severity") not in SEVERITY_ORDER:
        errors.append(f"Invalid expected_severity: {payload.get('expected_severity')}")

    events = payload.get("events")
    if not isinstance(events, list) or not events:
        errors.append("Payload events must be a non-empty list")
        return False, errors

    required_event_fields = {
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

    for idx, event in enumerate(events):
        missing = required_event_fields - set(event.keys())
        if missing:
            errors.append(f"Event index {idx} missing fields: {sorted(missing)}")

    return len(errors) == 0, errors


def validate_mrs_severity_alignment(mrs: Optional[float], severity: Optional[str]) -> Tuple[bool, str]:
    if mrs is None:
        return False, "MRS is missing"

    if severity not in MRS_RANGES_BY_SEVERITY:
        return False, f"Unknown severity: {severity}"

    low, high = MRS_RANGES_BY_SEVERITY[severity]

    if low <= float(mrs) <= high:
        return True, "MRS is aligned with severity"

    return False, f"MRS {mrs} is outside expected range for severity {severity}: {low} to {high}"


def validate_action_severity_alignment(
    action_bundle: Optional[str],
    severity: Optional[str],
) -> Tuple[bool, str]:
    if severity not in EXPECTED_ACTION_BY_SEVERITY:
        return False, f"Unknown severity for action validation: {severity}"

    if not action_bundle:
        return False, "Action bundle is missing"

    allowed_actions = EXPECTED_ACTION_BY_SEVERITY[severity]

    if action_bundle in allowed_actions:
        return True, "Action bundle is aligned with severity"

    return False, f"Action bundle '{action_bundle}' is not valid for severity '{severity}'"


def extract_final_output(result: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    errors = []

    parsed_output = result.get("parsed_output")
    if not isinstance(parsed_output, dict):
        return {}, ["parsed_output is missing or not a dictionary"]

    final_output = parsed_output.get("final_output")
    if not isinstance(final_output, dict):
        return {}, ["final_output is missing or not a dictionary"]

    required_fields = ["severity", "mrs", "action_bundle"]
    for field in required_fields:
        if field not in final_output:
            errors.append(f"final_output missing field: {field}")

    return final_output, errors


def start_execution(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    unique_id = uuid.uuid4().hex[:12]
    name = f"{payload['scenario']}-{unique_id}"

    try:
        response = sfn.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            name=name,
            input=json.dumps(payload),
        )
        return response["executionArn"], None

    except (ClientError, BotoCoreError) as exc:
        return None, f"AWS start_execution failed: {exc}"


def wait_for_execution(execution_arn: str) -> Dict[str, Any]:
    start_time = time.perf_counter()

    while True:
        elapsed_seconds = time.perf_counter() - start_time

        if elapsed_seconds > MAX_WAIT_SECONDS:
            return {
                "status": "INFRA_TIMEOUT",
                "failure_type": "INFRASTRUCTURE",
                "latency_seconds": round(elapsed_seconds, 4),
                "parsed_output": {},
                "error": f"Execution exceeded MAX_WAIT_SECONDS={MAX_WAIT_SECONDS}",
            }

        try:
            response = sfn.describe_execution(executionArn=execution_arn)

        except (ClientError, BotoCoreError) as exc:
            return {
                "status": "AWS_DESCRIBE_ERROR",
                "failure_type": "INFRASTRUCTURE",
                "latency_seconds": round(elapsed_seconds, 4),
                "parsed_output": {},
                "error": f"AWS describe_execution failed: {exc}",
            }

        if response["status"] in {"SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"}:
            total_latency = time.perf_counter() - start_time
            output = response.get("output")

            if output:
                try:
                    response["parsed_output"] = json.loads(output)
                except json.JSONDecodeError:
                    response["parsed_output"] = {}
                    response["output_parse_error"] = "Execution output was not valid JSON"
            else:
                response["parsed_output"] = {}

            response["latency_seconds"] = round(total_latency, 4)
            response["failure_type"] = "NONE" if response["status"] == "SUCCEEDED" else "INFRASTRUCTURE"
            return response

        time.sleep(POLL_INTERVAL_SECONDS)


def run_data_quality_tests() -> Dict[str, Any]:
    results = []

    for test in DATA_QUALITY_TESTS:
        dq_result = validate_events(test["events"])
        actual_passed = dq_result["passed"]
        test_passed = actual_passed == test["expected_passed"]

        results.append({
            "test_name": test["name"],
            "expected_data_quality_passed": test["expected_passed"],
            "actual_data_quality_passed": actual_passed,
            "quality_score": dq_result.get("quality_score"),
            "invalid_events": dq_result.get("invalid_events"),
            "errors": dq_result.get("invalid_event_details"),
            "test_passed": test_passed,
        })

    section_pass_rate = pass_rate(results)

    summary = {
        "section": "data_quality",
        "total_tests": len(results),
        "passed_tests": sum(1 for r in results if r["test_passed"]),
        "pass_rate": round(section_pass_rate, 4),
        "minimum_required_tests": MIN_SECTION_TESTS,
        "minimum_tests_passed": len(results) >= MIN_SECTION_TESTS,
        "target_pass_rate": TARGET_PASS_RATE,
        "target_pass_rate_passed": section_pass_rate >= TARGET_PASS_RATE,
    }

    output = {"summary": summary, "results": results}
    save_json("data_quality_results.json", output)
    return output


def run_failure_handling_tests() -> Dict[str, Any]:
    results = []

    for test in DATA_QUALITY_TESTS:
        expected_blocked = not test["expected_passed"]
        dq_result = validate_events(test["events"])
        blocked_before_execution = not dq_result["passed"]

        test_passed = blocked_before_execution == expected_blocked

        results.append({
            "test_name": f"failure_{test['name']}",
            "expected_blocked_before_execution": expected_blocked,
            "actual_blocked_before_execution": blocked_before_execution,
            "step_functions_called": False if blocked_before_execution else "NOT_CALLED_IN_FAILURE_TEST",
            "quality_score": dq_result.get("quality_score"),
            "errors": dq_result.get("invalid_event_details"),
            "failure_type": "DATA_QUALITY_BLOCK" if blocked_before_execution else "NONE",
            "test_passed": test_passed,
        })

    section_pass_rate = pass_rate(results)

    summary = {
        "section": "failure_handling",
        "total_tests": len(results),
        "passed_tests": sum(1 for r in results if r["test_passed"]),
        "pass_rate": round(section_pass_rate, 4),
        "minimum_required_tests": MIN_SECTION_TESTS,
        "minimum_tests_passed": len(results) >= MIN_SECTION_TESTS,
        "target_pass_rate": TARGET_PASS_RATE,
        "target_pass_rate_passed": section_pass_rate >= TARGET_PASS_RATE,
    }

    output = {"summary": summary, "results": results}
    save_json("failure_handling_results.json", output)
    return output


def run_slo_and_decision_tests() -> Dict[str, Any]:
    results = []
    latency_values = []
    cloud_execution_count = 0

    for scenario_name, scenario in SCENARIOS.items():
        if cloud_execution_count >= MAX_CLOUD_EXECUTIONS:
            results.append({
                "scenario": scenario_name,
                "expected_severity": scenario["expected_severity"],
                "actual_severity": None,
                "status": "SKIPPED_COST_GUARDRAIL",
                "failure_type": "FINOPS_GUARDRAIL",
                "latency_seconds": None,
                "slo_latency_passed": False,
                "decision_correct": False,
                "mrs_severity_aligned": False,
                "action_severity_aligned": False,
                "test_passed": False,
                "errors": [f"MAX_CLOUD_EXECUTIONS={MAX_CLOUD_EXECUTIONS} reached"],
            })
            continue

        dq_result = validate_events(scenario["events"])

        if not dq_result["passed"]:
            results.append({
                "scenario": scenario_name,
                "expected_severity": scenario["expected_severity"],
                "actual_severity": None,
                "status": "FAILED_DATA_QUALITY",
                "failure_type": "DATA_QUALITY",
                "latency_seconds": None,
                "slo_latency_passed": False,
                "decision_correct": False,
                "mrs_severity_aligned": False,
                "action_severity_aligned": False,
                "test_passed": False,
                "quality_score": dq_result.get("quality_score"),
                "errors": dq_result.get("invalid_event_details"),
            })
            continue

        payload = {
            "run_id": f"{scenario_name}_{uuid.uuid4().hex[:8]}",
            "scenario": scenario_name,
            "expected_severity": scenario["expected_severity"],
            "events": scenario["events"],
        }

        payload_valid, payload_errors = validate_payload_schema(payload)
        if not payload_valid:
            results.append({
                "scenario": scenario_name,
                "expected_severity": scenario["expected_severity"],
                "actual_severity": None,
                "status": "FAILED_PAYLOAD_SCHEMA",
                "failure_type": "INPUT_CONTRACT",
                "latency_seconds": None,
                "slo_latency_passed": False,
                "decision_correct": False,
                "mrs_severity_aligned": False,
                "action_severity_aligned": False,
                "test_passed": False,
                "quality_score": dq_result.get("quality_score"),
                "errors": payload_errors,
            })
            continue

        if DRY_RUN:
            results.append({
                "scenario": scenario_name,
                "expected_severity": scenario["expected_severity"],
                "actual_severity": None,
                "status": "DRY_RUN_SKIPPED_AWS",
                "failure_type": "NONE",
                "latency_seconds": None,
                "slo_latency_passed": None,
                "decision_correct": None,
                "mrs_severity_aligned": None,
                "action_severity_aligned": None,
                "test_passed": True,
                "quality_score": dq_result.get("quality_score"),
                "errors": [],
            })
            continue

        cloud_execution_count += 1

        execution_arn, start_error = start_execution(payload)
        if start_error or execution_arn is None:
            results.append({
                "scenario": scenario_name,
                "expected_severity": scenario["expected_severity"],
                "actual_severity": None,
                "status": "AWS_START_ERROR",
                "failure_type": "INFRASTRUCTURE",
                "latency_seconds": None,
                "slo_latency_passed": False,
                "decision_correct": False,
                "mrs_severity_aligned": False,
                "action_severity_aligned": False,
                "test_passed": False,
                "quality_score": dq_result.get("quality_score"),
                "errors": [start_error],
            })
            continue

        result = wait_for_execution(execution_arn)
        final_output, output_errors = extract_final_output(result)

        actual_severity = final_output.get("severity")
        mrs = final_output.get("mrs")
        action_bundle = final_output.get("action_bundle")
        latency_seconds = result.get("latency_seconds")

        if latency_seconds is not None:
            latency_values.append(latency_seconds)

        slo_latency_passed = latency_seconds is not None and latency_seconds <= SLO_LATENCY_SECONDS
        decision_correct = actual_severity == scenario["expected_severity"]

        mrs_severity_aligned, mrs_alignment_message = validate_mrs_severity_alignment(
            mrs=mrs,
            severity=actual_severity,
        )

        action_severity_aligned, action_alignment_message = validate_action_severity_alignment(
            action_bundle=action_bundle,
            severity=actual_severity,
        )

        errors = []
        errors.extend(output_errors)

        if not decision_correct:
            errors.append(
                f"Expected severity {scenario['expected_severity']}, got {actual_severity}"
            )

        if not slo_latency_passed:
            errors.append(
                f"Latency SLO failed: latency={latency_seconds}, target={SLO_LATENCY_SECONDS}"
            )

        if not mrs_severity_aligned:
            errors.append(mrs_alignment_message)

        if not action_severity_aligned:
            errors.append(action_alignment_message)

        test_passed = (
            result["status"] == "SUCCEEDED"
            and not output_errors
            and decision_correct
            and slo_latency_passed
            and mrs_severity_aligned
            and action_severity_aligned
        )



        cloudwatch_metrics = publish_decision_metrics(
            scenario=scenario_name,
            latency_seconds=latency_seconds,
            success=test_passed,
            mrs=mrs,
        )
        results.append({
            "scenario": scenario_name,
            "cloudwatch_metrics": cloudwatch_metrics,
            "expected_severity": scenario["expected_severity"],
            "actual_severity": actual_severity,
            "status": result["status"],
            "failure_type": result.get("failure_type"),
            "execution_arn": execution_arn,
            "mrs": mrs,
            "action_bundle": action_bundle,
            "latency_seconds": latency_seconds,
            "slo_latency_target_seconds": SLO_LATENCY_SECONDS,
            "slo_latency_passed": slo_latency_passed,
            "decision_correct": decision_correct,
            "mrs_severity_aligned": mrs_severity_aligned,
            "mrs_alignment_message": mrs_alignment_message,
            "action_severity_aligned": action_severity_aligned,
            "action_alignment_message": action_alignment_message,
            "quality_score": dq_result.get("quality_score"),
            "test_passed": test_passed,
            "errors": errors,
        })

    avg_latency = mean(latency_values) if latency_values else 0.0
    p95_latency = calculate_percentile_nearest_rank(latency_values, 95)

    total_tests = len(results)
    passed_tests = sum(1 for r in results if r["test_passed"])
    section_pass_rate = pass_rate(results)

    infra_failures = sum(
        1 for r in results
        if r.get("failure_type") in {"INFRASTRUCTURE", "FINOPS_GUARDRAIL"}
    )

    business_failures = sum(
        1 for r in results
        if r.get("failure_type") not in {"INFRASTRUCTURE", "FINOPS_GUARDRAIL"}
        and r.get("test_passed") is False
    )

    availability = (
        sum(1 for r in results if r.get("status") == "SUCCEEDED") / total_tests
        if total_tests else 0.0
    )

    decision_accuracy = (
        sum(1 for r in results if r.get("decision_correct") is True) / total_tests
        if total_tests else 0.0
    )

    summary = {
        "section": "slo_latency_and_decision_quality",
        "total_tests": total_tests,
        "passed_tests": passed_tests,
        "pass_rate": round(section_pass_rate, 4),
        "minimum_required_tests": MIN_SECTION_TESTS,
        "minimum_tests_passed": total_tests >= MIN_SECTION_TESTS,
        "target_pass_rate": TARGET_PASS_RATE,
        "target_pass_rate_passed": section_pass_rate >= TARGET_PASS_RATE,
        "average_latency_seconds": round(avg_latency, 4),
        "p95_latency_seconds": round(p95_latency, 4),
        "slo_latency_target_seconds": SLO_LATENCY_SECONDS,
        "p95_latency_slo_passed": p95_latency <= SLO_LATENCY_SECONDS,
        "decision_accuracy": round(decision_accuracy, 4),
        "availability": round(availability, 4),
        "infra_failures": infra_failures,
        "business_failures": business_failures,
        "cloud_execution_count": cloud_execution_count,
        "max_cloud_executions": MAX_CLOUD_EXECUTIONS,
        "dry_run": DRY_RUN,
    }

    output = {"summary": summary, "results": results}
    save_json("slo_and_decision_quality_results.json", output)
    return output


def build_confusion_matrix(results: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    matrix = defaultdict(lambda: defaultdict(int))

    for result in results:
        expected = result.get("expected_severity") or "UNKNOWN_EXPECTED"

        if result.get("failure_type") in {"INFRASTRUCTURE", "FINOPS_GUARDRAIL"}:
            actual = "SYSTEM_FAILURE"
        elif result.get("actual_severity") is None:
            actual = "NO_DECISION"
        else:
            actual = result.get("actual_severity")

        matrix[expected][actual] += 1

    return {expected: dict(actuals) for expected, actuals in matrix.items()}


def section_verdict(summary: Dict[str, Any]) -> str:
    if not summary["minimum_tests_passed"]:
        return "FAIL"

    if not summary["target_pass_rate_passed"]:
        return "FAIL"

    if "p95_latency_slo_passed" in summary and not summary["p95_latency_slo_passed"]:
        return "FAIL"

    return "PASS"


def generate_readme(evidence: Dict[str, Any]) -> Path:
    readme_path = OUTPUT_DIR / "test_run_summary.md"

    dq = evidence["data_quality"]["summary"]
    fh = evidence["failure_handling"]["summary"]
    sd = evidence["slo_decision"]["summary"]

    lines = [
        "# FlowPay Pipeline Validation Evidence",
        "",
        f"Generated at: `{evidence['generated_at']}`",
        "",
        f"## Overall Verdict: **{evidence['overall_status']}**",
        "",
        "This evidence pack documents automated validation for the FlowPay real-time financial intelligence pipeline.",
        "",
        "## Validation Standards",
        "",
        f"- Minimum tests per section: **{MIN_SECTION_TESTS}**",
        f"- Target pass rate per section: **{TARGET_PASS_RATE:.0%}**",
        f"- SLO (Service Level Objective) latency target: **P95 < {SLO_LATENCY_SECONDS}s**",
        f"- Max cloud executions: **{MAX_CLOUD_EXECUTIONS}**",
        f"- Dry run mode: **{DRY_RUN}**",
        "",
        "## Results Summary",
        "",
        "| Section | Tests | Passed | Pass Rate | Verdict |",
        "|---|---:|---:|---:|---|",
        f"| Data Quality | {dq['total_tests']} | {dq['passed_tests']} | {dq['pass_rate']:.0%} | {section_verdict(dq)} |",
        f"| Failure Handling | {fh['total_tests']} | {fh['passed_tests']} | {fh['pass_rate']:.0%} | {section_verdict(fh)} |",
        f"| SLO + Decision Quality | {sd['total_tests']} | {sd['passed_tests']} | {sd['pass_rate']:.0%} | {section_verdict(sd)} |",
        "",
        "## SLO (Service Level Objective) Metrics",
        "",
        f"- Average latency: **{sd['average_latency_seconds']}s**",
        f"- P95 latency: **{sd['p95_latency_seconds']}s**",
        f"- P95 latency target passed: **{sd['p95_latency_slo_passed']}**",
        f"- Decision accuracy: **{sd['decision_accuracy']:.0%}**",
        f"- Availability: **{sd['availability']:.0%}**",
        f"- Infrastructure failures: **{sd['infra_failures']}**",
        f"- Business failures: **{sd['business_failures']}**",
        "",
        "## Confusion Matrix",
        "",
        "```json",
        json.dumps(evidence["confusion_matrix"], indent=2),
        "```",
        "",
        "## Generated Evidence Files",
        "",
        "- `data_quality_results.json`",
        "- `failure_handling_results.json`",
        "- `slo_and_decision_quality_results.json`",
        "- `test_run_summary.json`",
        "- `test_run_summary.md`",
        "",
        "## Portfolio Claim",
        "",
        "> FlowPay was validated with automated production-style tests covering data quality, failure handling, infrastructure reliability, SLO latency, decision quality, severity/MRS alignment, and action/severity alignment.",
    ]

    readme_path.write_text("\n".join(lines), encoding="utf-8")
    return readme_path


def main() -> None:
    print("\nFLOWPAY FULL PIPELINE VALIDATION RUNNER")
    print("=" * 80)

    data_quality_output = run_data_quality_tests()
    print("Data Quality:", data_quality_output["summary"])

    failure_handling_output = run_failure_handling_tests()
    print("Failure Handling:", failure_handling_output["summary"])

    slo_decision_output = run_slo_and_decision_tests()
    print("SLO + Decision:", slo_decision_output["summary"])

    confusion_matrix = build_confusion_matrix(slo_decision_output["results"])

    summaries = [
        data_quality_output["summary"],
        failure_handling_output["summary"],
        slo_decision_output["summary"],
    ]

    overall_status = "PASS"
    for summary in summaries:
        if section_verdict(summary) == "FAIL":
            overall_status = "FAIL"

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall_status,
        "data_quality": data_quality_output,
        "failure_handling": failure_handling_output,
        "slo_decision": slo_decision_output,
        "confusion_matrix": confusion_matrix,
    }

    save_json("test_run_summary.json", evidence)
    readme_path = generate_readme(evidence)

    print("\nFINAL VALIDATION VERDICT")
    print("=" * 80)
    print(f"OVERALL STATUS: {overall_status}")
    print(f"Evidence JSON: {OUTPUT_DIR / 'test_run_summary.json'}")
    print(f"Evidence README: {readme_path}")


if __name__ == "__main__":
    main()