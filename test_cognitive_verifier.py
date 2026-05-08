from flowpay_cognitive_verifier import verify_decision


TEST_CASES = [
    {
        "name": "valid_normal_decision",
        "mrs": 0.1,
        "severity": "Normal",
        "action_bundle": "monitoring_bundle",
        "expected_passed": True,
    },
    {
        "name": "valid_guarded_decision",
        "mrs": 44.05,
        "severity": "Guarded",
        "action_bundle": "early_warning_bundle",
        "expected_passed": True,
    },
    {
        "name": "valid_defensive_decision",
        "mrs": 57.0,
        "severity": "Defensive",
        "action_bundle": "defensive_bundle",
        "expected_passed": True,
    },
    {
        "name": "valid_critical_decision",
        "mrs": 79.53,
        "severity": "Critical",
        "action_bundle": "critical_protection_bundle",
        "expected_passed": True,
    },
    {
        "name": "invalid_high_mrs_low_severity",
        "mrs": 80.0,
        "severity": "Normal",
        "action_bundle": "monitoring_bundle",
        "expected_passed": False,
    },
    {
        "name": "invalid_low_mrs_high_severity",
        "mrs": 10.0,
        "severity": "Critical",
        "action_bundle": "critical_protection_bundle",
        "expected_passed": False,
    },
    {
        "name": "invalid_action_for_severity",
        "mrs": 80.0,
        "severity": "Critical",
        "action_bundle": "monitoring_bundle",
        "expected_passed": False,
    },
    {
        "name": "missing_mrs",
        "mrs": None,
        "severity": "Normal",
        "action_bundle": "monitoring_bundle",
        "expected_passed": False,
    },
    {
        "name": "missing_action",
        "mrs": 44.0,
        "severity": "Guarded",
        "action_bundle": None,
        "expected_passed": False,
    },
    {
        "name": "unknown_severity",
        "mrs": 44.0,
        "severity": "Extreme",
        "action_bundle": "early_warning_bundle",
        "expected_passed": False,
    },
]


def main():
    print("\nFLOWPAY COGNITIVE VERIFIER TEST")
    print("=" * 80)

    passed_count = 0

    for test in TEST_CASES:
        result = verify_decision(
            mrs=test["mrs"],
            severity=test["severity"],
            action_bundle=test["action_bundle"],
        )

        actual_passed = result["cognitive_verifier_passed"]
        test_passed = actual_passed == test["expected_passed"]

        if test_passed:
            passed_count += 1

        print(
            f"{'PASS' if test_passed else 'FAIL'} | "
            f"{test['name']} | Expected: {test['expected_passed']} | "
            f"Actual: {actual_passed}"
        )

    total = len(TEST_CASES)
    print("\nSUMMARY")
    print("=" * 80)
    print(f"Passed: {passed_count}/{total}")
    print(f"Pass Rate: {passed_count / total:.2%}")
    print(f"TEST RESULT: {'PASS' if passed_count == total else 'FAIL'}")


if __name__ == "__main__":
    main()