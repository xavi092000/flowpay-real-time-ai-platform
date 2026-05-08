from flowpay_observability import publish_decision_metrics


def main():
    print("\nFLOWPAY CLOUDWATCH METRICS TEST")
    print("=" * 80)

    result = publish_decision_metrics(
        scenario="cloudwatch_test",
        latency_seconds=1.23,
        success=True,
        mrs=42.0,
    )

    print(result)

    test_passed = all(result.values())

    print(f"\nTEST RESULT: {'PASS' if test_passed else 'FAIL'}")


if __name__ == "__main__":
    main()