from __future__ import annotations

from collections import Counter
from typing import Any


SEVERITY_ORDER = {
    "Normal": 1,
    "Guarded": 2,
    "Defensive": 3,
    "Critical": 4,
}


def compute_decision_quality_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    total_windows = len(records)

    if total_windows == 0:
        return {
            "total_windows": 0,
            "status": "DATA_NOT_AVAILABLE",
        }

    mrs_values: list[float] = []
    severities: list[str] = []
    bundles: list[str] = []
    human_reviews = 0
    escalations = 0
    high_confidence_windows = 0

    for record in records:
        final_output = record.get("agent_decision", {}).get("final_output", {})
        agents = record.get("agent_decision", {}).get("agents", {})

        mrs = final_output.get("mrs")
        severity = final_output.get("severity", "DATA_NOT_AVAILABLE")
        bundle = final_output.get("action_bundle", "DATA_NOT_AVAILABLE")
        human_review_required = final_output.get("human_review_required", False)
        technical_confidence = final_output.get("technical_confidence", "low")

        triage = agents.get("signal_triage", {})
        escalation_required = triage.get("escalation_required", False)

        if isinstance(mrs, (int, float)):
            mrs_values.append(float(mrs))

        severities.append(severity)
        bundles.append(bundle)

        if human_review_required:
            human_reviews += 1

        if escalation_required:
            escalations += 1

        if technical_confidence == "high":
            high_confidence_windows += 1

    avg_mrs = round(sum(mrs_values) / len(mrs_values), 2) if mrs_values else None
    max_mrs = round(max(mrs_values), 2) if mrs_values else None
    min_mrs = round(min(mrs_values), 2) if mrs_values else None

    escalation_rate = round(escalations / total_windows, 4)
    human_review_rate = round(human_reviews / total_windows, 4)
    technical_confidence_rate = round(high_confidence_windows / total_windows, 4)

    severity_distribution = dict(Counter(severities))
    bundle_distribution = dict(Counter(bundles))

    mrs_trend = classify_mrs_trend(mrs_values)
    decision_stability = classify_decision_stability(severities)

    return {
        "total_windows": total_windows,
        "avg_mrs": avg_mrs,
        "max_mrs": max_mrs,
        "min_mrs": min_mrs,
        "mrs_trend": mrs_trend,
        "decision_stability": decision_stability,
        "escalation_rate": escalation_rate,
        "human_review_rate": human_review_rate,
        "technical_confidence_rate": technical_confidence_rate,
        "severity_distribution": severity_distribution,
        "bundle_distribution": bundle_distribution,
        "business_interpretation": {
            "summary": (
                "The system measured decision quality across all replay windows."
            ),
            "in_practice": (
                "In practice, these metrics show how often FlowPay escalates risk, "
                "requires human review, and maintains technical confidence."
            ),
            "this_means": (
                "This means the platform is not only making decisions, but also "
                "measuring whether those decisions are stable, explainable, and operationally safe."
            ),
        },
    }


def classify_mrs_trend(mrs_values: list[float]) -> str:
    if len(mrs_values) < 2:
        return "DATA_NOT_AVAILABLE"

    first = mrs_values[0]
    last = mrs_values[-1]

    if last > first * 1.15:
        return "increasing"
    if last < first * 0.85:
        return "decreasing"
    return "stable"


def classify_decision_stability(severities: list[str]) -> str:
    if len(severities) < 2:
        return "DATA_NOT_AVAILABLE"

    severity_numbers = [
        SEVERITY_ORDER.get(severity, 0)
        for severity in severities
    ]

    direction_changes = 0

    for i in range(2, len(severity_numbers)):
        previous_delta = severity_numbers[i - 1] - severity_numbers[i - 2]
        current_delta = severity_numbers[i] - severity_numbers[i - 1]

        if previous_delta * current_delta < 0:
            direction_changes += 1

    if direction_changes == 0:
        return "stable"
    if direction_changes == 1:
        return "moderate"
    return "unstable"