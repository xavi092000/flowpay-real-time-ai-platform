import json
from collections import defaultdict


INPUT_FILE = "flowpay_slo_results.json"
OUTPUT_FILE = "flowpay_decision_quality_results.json"


def main():
    print("\nFLOWPAY DECISION QUALITY METRICS")
    print("=" * 80)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = data.get("results", [])

    total = len(results)
    correct = 0
    confusion_matrix = defaultdict(lambda: defaultdict(int))

    scenario_results = []

    for result in results:
        expected = result.get("expected_severity")
        actual = result.get("actual_severity")
        scenario = result.get("scenario")

        is_correct = expected == actual

        if is_correct:
            correct += 1

        confusion_matrix[expected][actual] += 1

        scenario_results.append({
            "scenario": scenario,
            "expected_severity": expected,
            "actual_severity": actual,
            "decision_correct": is_correct,
            "mrs": result.get("mrs"),
            "action_bundle": result.get("action_bundle"),
            "latency_seconds": result.get("latency_seconds"),
        })

        print(
            f"{'PASS' if is_correct else 'FAIL'} | "
            f"{scenario} | Expected: {expected} | Actual: {actual}"
        )

    accuracy = correct / total if total > 0 else 0.0

    print("\nSUMMARY")
    print("=" * 80)
    print(f"Correct Decisions: {correct}/{total}")
    print(f"Decision Accuracy: {accuracy:.2%}")

    print("\nCONFUSION MATRIX")
    print("=" * 80)

    for expected, actuals in confusion_matrix.items():
        for actual, count in actuals.items():
            print(f"Expected {expected} -> Actual {actual}: {count}")

    output = {
        "summary": {
            "total_decisions": total,
            "correct_decisions": correct,
            "decision_accuracy": round(accuracy, 4),
        },
        "confusion_matrix": {
            expected: dict(actuals)
            for expected, actuals in confusion_matrix.items()
        },
        "scenario_results": scenario_results,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()