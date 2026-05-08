from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------
# 1. SIGNAL TRIAGE
# ---------------------------
def signal_triage_agent(quant_decision: dict[str, Any]) -> dict[str, Any]:
    mrs = safe_float(quant_decision.get("market_risk_score"))
    severity = quant_decision.get("severity", "Unknown")

    if severity == "Normal":
        triage_action = "monitor_only"
        escalation_required = False
    elif severity == "Guarded":
        triage_action = "increase_monitoring"
        escalation_required = False
    elif severity == "Defensive":
        triage_action = "escalate_to_market_analysis"
        escalation_required = True
    elif severity == "Critical":
        triage_action = "immediate_escalation"
        escalation_required = True
    else:
        triage_action = "manual_review"
        escalation_required = True

    return {
        "agent": "signal_triage_agent",
        "timestamp": utc_now_iso(),
        "mrs": mrs,
        "severity": severity,
        "triage_action": triage_action,
        "escalation_required": escalation_required,
    }


# ---------------------------
# 2. MARKET ANALYSIS
# ---------------------------
def market_analysis_agent(
    quant_decision: dict[str, Any],
    triage_result: dict[str, Any],
) -> dict[str, Any]:
    severity = quant_decision.get("severity", "Unknown")
    metrics = quant_decision.get("metrics", {})

    signal_scores = {
        "order_flow_imbalance": safe_float(metrics.get("ofi_score")),
        "liquidity_stress": safe_float(metrics.get("liquidity_score")),
        "volatility_instability": safe_float(metrics.get("volatility_score")),
        "execution_risk": safe_float(metrics.get("execution_score")),
        "trend_deterioration": safe_float(metrics.get("trend_score")),
    }

    dominant_signal = max(signal_scores, key=signal_scores.get)

    if severity == "Normal":
        action_bundle = "monitoring_bundle"
    elif severity == "Guarded":
        action_bundle = "early_warning_bundle"
    elif severity == "Defensive":
        action_bundle = "defensive_bundle"
    elif severity == "Critical":
        action_bundle = "critical_protection_bundle"
    else:
        action_bundle = "manual_review_bundle"

    return {
        "agent": "market_analysis_agent",
        "timestamp": utc_now_iso(),
        "severity": severity,
        "dominant_signal": dominant_signal,
        "signal_scores": signal_scores,
        "action_bundle": action_bundle,
    }


# ---------------------------
# 3. GOVERNANCE
# ---------------------------
def governance_validation_agent(
    quant_decision: dict[str, Any],
    market_analysis: dict[str, Any],
) -> dict[str, Any]:
    severity = quant_decision.get("severity", "Unknown")
    action_bundle = market_analysis.get("action_bundle")

    human_review_required = severity in {"Defensive", "Critical"}

    return {
        "agent": "governance_validation_agent",
        "timestamp": utc_now_iso(),
        "allowed": True,
        "human_review_required": human_review_required,
    }


# ---------------------------
# 4. OBSERVABILITY
# ---------------------------
def observability_agent(
    events_window: list[dict[str, Any]],
) -> dict[str, Any]:
    total_events = len(events_window)

    return {
        "agent": "observability_agent",
        "timestamp": utc_now_iso(),
        "total_events": total_events,
        "technical_confidence": "high" if total_events > 0 else "low",
    }


# ---------------------------
# 5. RAG CONTEXT BUILDER (NEW)
# ---------------------------
def rag_context_builder_agent(
    quant_decision: dict[str, Any],
    market_analysis: dict[str, Any],
    governance_result: dict[str, Any],
    observability_result: dict[str, Any],
) -> dict[str, Any]:

    return {
        "agent": "rag_context_builder_agent",
        "timestamp": utc_now_iso(),

        "facts_for_rag": {
            "severity": quant_decision.get("severity", "DATA_NOT_AVAILABLE"),
            "market_risk_score": quant_decision.get("market_risk_score", "DATA_NOT_AVAILABLE"),
            "dominant_signal": market_analysis.get("dominant_signal", "DATA_NOT_AVAILABLE"),
            "action_bundle": market_analysis.get("action_bundle", "DATA_NOT_AVAILABLE"),

            "governance_allowed": governance_result.get("allowed", False),
            "human_review_required": governance_result.get("human_review_required", True),

            "technical_confidence": observability_result.get("technical_confidence", "low"),
        }
    }


# ---------------------------
# MAIN PIPELINE
# ---------------------------
def run_decision_agents(
    events_window: list[dict[str, Any]],
    quant_decision: dict[str, Any],
) -> dict[str, Any]:

    triage = signal_triage_agent(quant_decision)

    market_analysis = market_analysis_agent(
        quant_decision,
        triage,
    )

    governance = governance_validation_agent(
        quant_decision,
        market_analysis,
    )

    observability = observability_agent(events_window)

    rag_context = rag_context_builder_agent(
        quant_decision,
        market_analysis,
        governance,
        observability,
    )

    return {
        "decision_timestamp": utc_now_iso(),
        "agents": {
            "signal_triage": triage,
            "market_analysis": market_analysis,
            "governance_validation": governance,
            "observability": observability,
            "rag_context": rag_context,
        },
        "final_output": {
            "severity": quant_decision.get("severity"),
            "mrs": quant_decision.get("market_risk_score"),
            "action_bundle": market_analysis.get("action_bundle"),
            "human_review_required": governance.get("human_review_required"),
            "technical_confidence": observability.get("technical_confidence"),
        },
    }