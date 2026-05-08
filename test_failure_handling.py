from flowpay_data_quality import validate_events


invalid_scenario = {
    "scenario": "invalid_market_event",
    "expected_behavior": "BLOCK_BEFORE_EXECUTION",
    "events": [
        {
            "event_id": "evt_invalid_001",
            "timestamp": "2026-04-28T10:05:00Z",
            "symbol": "BTC-USD",
            "side": "hold",
            "price": -100,
            "volume": 0,
            "bid": 67000,
            "ask": 66900,
            "bid_depth": -1,
            "ask_depth": 0,
        }
    ],
}


def main():
    print("\nFLOWPAY FAILURE HANDLING TEST")
    print("=" * 80)

    dq_result = validate_events(invalid_scenario["events"])

    blocked_before_execution = not dq_result["passed"]

    print(f"Scenario: {invalid_scenario['scenario']}")
    print(f"Expected Behavior: {invalid_scenario['expected_behavior']}")
    print(f"Data Quality Passed: {dq_result['passed']}")
    print(f"Blocked Before Execution: {blocked_before_execution}")
    print(f"Quality Score: {dq_result['quality_score']}")
    print(f"Invalid Events: {dq_result['invalid_events']}")
    print(f"Errors: {dq_result['invalid_event_details']}")

    test_passed = blocked_before_execution

    print(f"\nTEST RESULT: {'PASS' if test_passed else 'FAIL'}")


if __name__ == "__main__":
    main()