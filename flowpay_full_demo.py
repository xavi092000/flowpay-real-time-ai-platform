import json
from typing import Any

from flowpay_event_scenarios import build_scenarios
from flowpay_quant_engine import compute_quant_decision
from flowpay_rag_with_quant import run_flowpay_rag


def print_decision_summary(scenario_name: str, decision: dict[str, Any]) -> None:
    governance = decision.get("governance_status", {})

    print("\n" + "=" * 80)
    print(f"Scenario: {scenario_name}")
    print("-" * 80)
    print(f"Symbol: {decision.get('symbol')}")
    print(f"Market Risk Score: {decision.get('market_risk_score')}")
    print(f"Severity: {decision.get('severity')}")
    print(f"Dominant Problem: {decision.get('dominant_problem')}")
    print(f"Recommended Action: {decision.get('recommended_action')}")
    print(f"Human Review Required: {governance.get('requires_human_review')}")
    print(f"Governance Approved: {governance.get('approved')}")


def print_rag_summary(rag_output: dict[str, Any]) -> None:
    print("\nRAG Explanation:")
    print(rag_output.get("explanation", ""))

    print("\nRAG Confidence:")
    print(json.dumps(rag_output.get("retrieval_confidence", {}), indent=2))

    print("\nEstimated Cost:")
    print(json.dumps(rag_output.get("cost", {}), indent=2))

    print("\nLatency:")
    print(json.dumps(rag_output.get("latency", {}), indent=2))


def run_full_demo() -> None:
    scenarios = build_scenarios(add_noise=True)

    previous_mrs_values = [22.5, 28.1, 31.4]

    print("\nFLOWPAY FULL DEMO — EVENT SCENARIOS + QUANT + RAG")
    print("=" * 80)
    print(f"Loaded scenarios: {len(scenarios)}")

    for scenario_name, events in scenarios.items():
        decision = compute_quant_decision(
            events=events,
            previous_mrs_values=previous_mrs_values,
        )

        print_decision_summary(scenario_name, decision)

        rag_output = run_flowpay_rag(decision)
        print_rag_summary(rag_output)

        previous_mrs_values.append(float(decision["market_risk_score"]))

    print("\n" + "=" * 80)
    print("FLOWPAY FULL DEMO COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    run_full_demo()