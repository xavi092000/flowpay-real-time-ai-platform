import json
import os
from datetime import datetime, timezone
from typing import Any

import boto3

s3 = boto3.client("s3")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def validate_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        raise ValueError("No events provided")

    for i, event in enumerate(events):
        if not event.get("timestamp"):
            raise ValueError(f"Event {i} missing timestamp")

        price = safe_float(event.get("price"))
        bid = safe_float(event.get("bid"))
        ask = safe_float(event.get("ask"))
        volume = safe_float(event.get("volume"))
        bid_depth = safe_float(event.get("bid_depth"))
        ask_depth = safe_float(event.get("ask_depth"))

        if price <= 0 or bid <= 0 or ask <= 0:
            raise ValueError(f"Invalid price/bid/ask at event {i}")

        if ask < bid:
            raise ValueError(f"Ask < bid at event {i}")

        if volume <= 0:
            raise ValueError(f"Invalid volume at event {i}")

        if bid_depth <= 0 or ask_depth <= 0:
            raise ValueError(f"Invalid depth at event {i}")

        if event.get("side") not in {"buy", "sell"}:
            raise ValueError(f"Invalid side at event {i}")

    return {
        "total_events": len(events),
        "invalid_events": 0,
        "invalid_rate": 0.0,
        "technical_confidence": "high",
    }


def default_events() -> list[dict[str, Any]]:
    return [
        {
            "timestamp": "2026-04-24T10:00:00Z",
            "symbol": "BTC-USD",
            "side": "buy",
            "price": 67000,
            "volume": 1.2,
            "bid": 66990,
            "ask": 67010,
            "bid_depth": 600000,
            "ask_depth": 610000,
        },
        {
            "timestamp": "2026-04-24T10:00:15Z",
            "symbol": "BTC-USD",
            "side": "buy",
            "price": 67020,
            "volume": 1.0,
            "bid": 67000,
            "ask": 67030,
            "bid_depth": 590000,
            "ask_depth": 600000,
        },
        {
            "timestamp": "2026-04-24T10:01:00Z",
            "symbol": "BTC-USD",
            "side": "sell",
            "price": 66800,
            "volume": 5.0,
            "bid": 66780,
            "ask": 66840,
            "bid_depth": 500000,
            "ask_depth": 580000,
        },
        {
            "timestamp": "2026-04-24T10:01:15Z",
            "symbol": "BTC-USD",
            "side": "sell",
            "price": 66650,
            "volume": 6.0,
            "bid": 66600,
            "ask": 66700,
            "bid_depth": 420000,
            "ask_depth": 560000,
        },
        {
            "timestamp": "2026-04-24T10:02:00Z",
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
            "timestamp": "2026-04-24T10:02:15Z",
            "symbol": "BTC-USD",
            "side": "sell",
            "price": 65200,
            "volume": 8.5,
            "bid": 65000,
            "ask": 65500,
            "bid_depth": 216000,
            "ask_depth": 504000,
        },
    ]


def compute_quant_decision(events: list[dict[str, Any]]) -> dict[str, Any]:
    validation = validate_events(events)

    buy_volume = sum(
        safe_float(event.get("volume"))
        for event in events
        if event.get("side") == "buy"
    )
    sell_volume = sum(
        safe_float(event.get("volume"))
        for event in events
        if event.get("side") == "sell"
    )

    total_volume = buy_volume + sell_volume
    ofi = abs(buy_volume - sell_volume) / total_volume if total_volume else 0.0
    ofi_score = round(ofi * 100, 2)

    depth_start = safe_float(events[0].get("bid_depth")) + safe_float(events[0].get("ask_depth"))
    depth_end = safe_float(events[-1].get("bid_depth")) + safe_float(events[-1].get("ask_depth"))
    depth_drop_pct = max(0.0, (depth_start - depth_end) / depth_start) if depth_start else 0.0
    liquidity_score = round(min(100.0, depth_drop_pct * 300), 2)

    prices = [safe_float(event.get("price")) for event in events]
    price_start = prices[0]
    price_end = prices[-1]
    high_price = max(prices)
    low_price = min(prices)

    close_to_close_move_pct = abs(price_end - price_start) / price_start if price_start else 0.0
    high_low_range_pct = (high_price - low_price) / price_start if price_start else 0.0

    volatility_score = round(
        min(100.0, (close_to_close_move_pct + high_low_range_pct) * 400),
        2,
    )

    spreads = []
    for event in events:
        bid = safe_float(event.get("bid"))
        ask = safe_float(event.get("ask"))
        mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0.0
        if mid > 0 and ask >= bid:
            spreads.append((ask - bid) / mid)

    average_spread_pct = sum(spreads) / len(spreads) if spreads else 0.0
    execution_score = round(min(100.0, average_spread_pct * 2000), 2)

    market_risk_score = round(
        0.35 * ofi_score
        + 0.30 * liquidity_score
        + 0.20 * volatility_score
        + 0.15 * execution_score,
        2,
    )

    if market_risk_score < 25:
        severity = "Normal"
        recommended_action = "monitor_only"
    elif market_risk_score < 50:
        severity = "Guarded"
        recommended_action = "increase_monitoring"
    elif market_risk_score < 75:
        severity = "Defensive"
        recommended_action = "liquidity_rebalancing"
    else:
        severity = "Critical"
        recommended_action = "survival_mode"

    signal_scores = {
        "order_flow_imbalance": ofi_score,
        "liquidity_stress": liquidity_score,
        "volatility_instability": volatility_score,
        "execution_risk": execution_score,
    }

    dominant_problem = max(signal_scores, key=signal_scores.get)

    return {
        "timestamp_utc": utc_now_iso(),
        "symbol": events[-1].get("symbol", "DATA_NOT_AVAILABLE"),
        "window": {
            "start_utc": events[0].get("timestamp"),
            "end_utc": events[-1].get("timestamp"),
            "event_count": len(events),
        },
        "data_quality": validation,
        "metrics": {
            "ofi_score": ofi_score,
            "liquidity_score": liquidity_score,
            "volatility_score": volatility_score,
            "execution_score": execution_score,
            "market_risk_score": market_risk_score,
        },
        "market_risk_score": market_risk_score,
        "severity": severity,
        "dominant_problem": dominant_problem,
        "recommended_action": recommended_action,
        "action_mode": "recommendation_only",
        "model_limitations": [
            "Scores are heuristic and not yet statistically calibrated.",
            "Thresholds require backtesting before production trading use.",
            "This engine produces recommendations only, not automated execution.",
        ],
    }


def run_decision_agents(
    quant_decision: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    severity = quant_decision["severity"]
    mrs = quant_decision["market_risk_score"]
    metrics = quant_decision["metrics"]

    triage_action = {
        "Normal": "monitor_only",
        "Guarded": "increase_monitoring",
        "Defensive": "escalate_to_market_analysis",
        "Critical": "immediate_escalation",
    }.get(severity, "manual_review")

    escalation_required = severity in {"Defensive", "Critical"}

    signal_scores = {
        "order_flow_imbalance": metrics.get("ofi_score", 0),
        "liquidity_stress": metrics.get("liquidity_score", 0),
        "volatility_instability": metrics.get("volatility_score", 0),
        "execution_risk": metrics.get("execution_score", 0),
    }

    dominant_signal = max(signal_scores, key=signal_scores.get)

    action_bundle = {
        "Normal": "monitoring_bundle",
        "Guarded": "early_warning_bundle",
        "Defensive": "defensive_bundle",
        "Critical": "critical_protection_bundle",
    }.get(severity, "manual_review_bundle")

    recommended_actions = {
        "monitoring_bundle": [
            "continue_monitoring",
            "keep_current_risk_limits",
        ],
        "early_warning_bundle": [
            "increase_monitoring_frequency",
            "tighten_slippage_tracking",
            "prepare_defensive_controls",
        ],
        "defensive_bundle": [
            "apply_spread_control",
            "reduce_exposure_scaling",
            "activate_smart_routing",
            "require_human_review",
        ],
        "critical_protection_bundle": [
            "activate_circuit_breaker_review",
            "apply_order_throttling",
            "force_survival_mode",
            "require_immediate_human_review",
        ],
    }.get(action_bundle, ["require_manual_investigation"])

    restricted_actions = {
        "activate_circuit_breaker_review",
        "force_survival_mode",
        "apply_order_throttling",
    }

    has_restricted_action = any(
        action in restricted_actions for action in recommended_actions
    )

    human_review_required = severity in {"Defensive", "Critical"} or has_restricted_action

    governance_allowed = True
    violations = []

    if severity == "Normal" and action_bundle != "monitoring_bundle":
        governance_allowed = False
        violations.append("Normal severity cannot trigger defensive or critical actions.")

    if severity == "Guarded" and action_bundle in {
        "defensive_bundle",
        "critical_protection_bundle",
    }:
        governance_allowed = False
        violations.append("Guarded severity cannot trigger high-impact actions.")

    data_quality = quant_decision.get("data_quality", {})
    technical_confidence = data_quality.get("technical_confidence", "low")

    facts_for_report = {
        "severity": severity,
        "market_risk_score": mrs,
        "dominant_signal": dominant_signal,
        "action_bundle": action_bundle,
        "recommended_actions": recommended_actions,
        "governance_allowed": governance_allowed,
        "human_review_required": human_review_required,
        "technical_confidence": technical_confidence,
    }

    return {
        "decision_timestamp": utc_now_iso(),
        "agents": {
            "signal_triage": {
                "agent": "signal_triage_agent",
                "timestamp": utc_now_iso(),
                "mrs": mrs,
                "severity": severity,
                "triage_action": triage_action,
                "escalation_required": escalation_required,
                "reason": f"Severity {severity} mapped to {triage_action}.",
            },
            "market_analysis": {
                "agent": "market_analysis_agent",
                "timestamp": utc_now_iso(),
                "dominant_signal": dominant_signal,
                "signal_scores": signal_scores,
                "action_bundle": action_bundle,
                "recommended_actions": recommended_actions,
                "reason": f"Dominant signal is {dominant_signal}.",
            },
            "governance_validation": {
                "agent": "governance_validation_agent",
                "timestamp": utc_now_iso(),
                "allowed": governance_allowed,
                "human_review_required": human_review_required,
                "restricted_action_detected": has_restricted_action,
                "violations": violations,
            },
            "observability": {
                "agent": "observability_agent",
                "timestamp": utc_now_iso(),
                "total_events": len(events),
                "technical_confidence": technical_confidence,
                "invalid_rate": data_quality.get("invalid_rate", "DATA_NOT_AVAILABLE"),
            },
            "rag_genai_explanation": {
                "agent": "rag_genai_explanation_agent",
                "timestamp": utc_now_iso(),
                "role": "build_grounded_context_for_decision_intelligence_report",
                "facts_for_report": facts_for_report,
                "grounding_policy": "deterministic_facts_only",
            },
        },
        "final_output": {
            "severity": severity,
            "mrs": mrs,
            "action_bundle": action_bundle,
            "recommended_actions": recommended_actions,
            "human_review_required": human_review_required,
            "governance_allowed": governance_allowed,
            "technical_confidence": technical_confidence,
        },
    }


def build_decision_intelligence_report(agent_decision: dict[str, Any]) -> dict[str, Any]:
    facts = agent_decision["agents"]["rag_genai_explanation"]["facts_for_report"]

    return {
        "report_type": "Decision Intelligence Report",
        "generated_at": utc_now_iso(),
        "summary": (
            f"FlowPay classified the market state as {facts['severity']} "
            f"with a Market Risk Score of {facts['market_risk_score']}."
        ),
        "supported_evidence": {
            "dominant_signal": facts["dominant_signal"],
            "action_bundle": facts["action_bundle"],
            "technical_confidence": facts["technical_confidence"],
        },
        "analysis": (
            f"The dominant signal is {facts['dominant_signal']}. "
            f"The selected action bundle is {facts['action_bundle']}."
        ),
        "recommendation": (
            f"Governance allowed: {facts['governance_allowed']}. "
            f"Human review required: {facts['human_review_required']}."
        ),
        "safety_note": (
            "The quant engine computes risk. The explanation layer only explains validated facts "
            "and does not override deterministic controls."
        ),
        "grounding_mode": "deterministic_facts_only",
        "confidence_label": "medium",
    }


def compute_decision_quality_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)

    if total == 0:
        return {
            "status": "DATA_NOT_AVAILABLE",
            "reason": "No successful records available.",
        }

    mrs_values = [
        record["agent_decision"]["final_output"]["mrs"]
        for record in records
    ]

    human_review_count = sum(
        1
        for record in records
        if record["agent_decision"]["final_output"]["human_review_required"]
    )

    escalation_count = sum(
        1
        for record in records
        if record["agent_decision"]["agents"]["signal_triage"]["escalation_required"]
    )

    high_confidence_count = sum(
        1
        for record in records
        if record["agent_decision"]["final_output"]["technical_confidence"] == "high"
    )

    return {
        "total_windows": total,
        "avg_mrs": round(sum(mrs_values) / total, 2),
        "max_mrs": max(mrs_values),
        "min_mrs": min(mrs_values),
        "mrs_trend": "increasing" if mrs_values[-1] > mrs_values[0] else "stable",
        "escalation_rate": round(escalation_count / total, 4),
        "human_review_rate": round(human_review_count / total, 4),
        "technical_confidence_rate": round(high_confidence_count / total, 4),
        "business_interpretation": {
            "in_practice": (
                "In practice, FlowPay measures risk escalation, human review, "
                "and technical confidence across decision windows."
            ),
            "this_means": (
                "This means the platform is measurable, auditable, and safer to operate."
            ),
        },
    }


def compute_finops_metrics(event_count: int, windows_processed: int = 1) -> dict[str, Any]:
    estimated_lambda_cost_usd = 0.000001
    estimated_stepfunctions_cost_usd = 0.000025
    estimated_s3_put_cost_usd = 0.00001
    estimated_athena_cost_usd = 0.0

    total_estimated_cost_usd = round(
        estimated_lambda_cost_usd
        + estimated_stepfunctions_cost_usd
        + estimated_s3_put_cost_usd
        + estimated_athena_cost_usd,
        8,
    )

    cost_per_decision_usd = round(
        total_estimated_cost_usd / windows_processed,
        8,
    )

    return {
        "event_count": event_count,
        "windows_processed": windows_processed,
        "estimated_lambda_cost_usd": estimated_lambda_cost_usd,
        "estimated_stepfunctions_cost_usd": estimated_stepfunctions_cost_usd,
        "estimated_s3_put_cost_usd": estimated_s3_put_cost_usd,
        "estimated_athena_cost_usd": estimated_athena_cost_usd,
        "total_estimated_cost_usd": total_estimated_cost_usd,
        "cost_per_decision_usd": cost_per_decision_usd,
        "finops_note": "Estimated demo cost only. Actual AWS billing should be validated with Cost Explorer.",
    }


def put_json_safe(bucket: str, key: str, payload: dict[str, Any]) -> None:
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=(json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"),
        ContentType="application/json",
    )


def get_state_and_step(event: dict[str, Any]) -> tuple[dict[str, Any], str]:
    state = event.get("state") or event
    step = event.get("step") or state.get("step") or "full_pipeline"
    return state, step


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    bucket = os.environ["FLOWPAY_BUCKET"]

    state, step = get_state_and_step(event)

    run_id = state.get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    events = state.get("events")

    if not events:
        events = default_events()

    try:
        if step == "validate_input":
            validation = validate_events(events)
            state.update(
                {
                    "run_id": run_id,
                    "events": events,
                    "validation": validation,
                    "last_completed_step": "validate_input",
                }
            )
            return state

        if step == "run_quant_decision":
            quant_decision = compute_quant_decision(events)
            state.update(
                {
                    "run_id": run_id,
                    "events": events,
                    "quant_decision": quant_decision,
                    "last_completed_step": "run_quant_decision",
                }
            )
            return state

        if "quant_decision" not in state:
            state["quant_decision"] = compute_quant_decision(events)

        quant_decision = state["quant_decision"]
        full_agent_decision = run_decision_agents(quant_decision, events)

        existing_agent_decision = state.get(
            "agent_decision",
            {
                "decision_timestamp": utc_now_iso(),
                "agents": {},
                "final_output": {},
            },
        )

        if step == "signal_triage":
            existing_agent_decision["agents"]["signal_triage"] = full_agent_decision["agents"]["signal_triage"]
            existing_agent_decision["final_output"] = full_agent_decision["final_output"]
            state["agent_decision"] = existing_agent_decision
            state["last_completed_step"] = "signal_triage"
            return state

        if step == "market_analysis":
            existing_agent_decision["agents"]["market_analysis"] = full_agent_decision["agents"]["market_analysis"]
            existing_agent_decision["final_output"] = full_agent_decision["final_output"]
            state["agent_decision"] = existing_agent_decision
            state["last_completed_step"] = "market_analysis"
            return state

        if step == "governance_validation":
            existing_agent_decision["agents"]["governance_validation"] = full_agent_decision["agents"]["governance_validation"]
            existing_agent_decision["final_output"] = full_agent_decision["final_output"]
            state["agent_decision"] = existing_agent_decision
            state["last_completed_step"] = "governance_validation"
            return state

        if step == "observability_check":
            existing_agent_decision["agents"]["observability"] = full_agent_decision["agents"]["observability"]
            existing_agent_decision["final_output"] = full_agent_decision["final_output"]
            state["agent_decision"] = existing_agent_decision
            state["last_completed_step"] = "observability_check"
            return state

        if step == "generate_decision_report":
            state["agent_decision"] = full_agent_decision
            state["decision_intelligence_report"] = build_decision_intelligence_report(full_agent_decision)
            state["last_completed_step"] = "generate_decision_report"
            return state

        if step in {"write_outputs", "full_pipeline"}:
            if step == "full_pipeline":
                quant_decision = compute_quant_decision(events)
                agent_decision = run_decision_agents(quant_decision, events)
                decision_report = build_decision_intelligence_report(agent_decision)
            else:
                agent_decision = state["agent_decision"]
                decision_report = state["decision_intelligence_report"]

            record = {
                "run_id": run_id,
                "scenario": state.get("scenario", "DATA_NOT_AVAILABLE"),
                "expected_severity": state.get("expected_severity", "DATA_NOT_AVAILABLE"),
                "event_count": len(events),
                "events": events,
                "quant_decision": quant_decision,
                "agent_decision": agent_decision,
                "decision_intelligence_report": decision_report,
            }

            summary = {
                "run_id": run_id,
                "scenario": state.get("scenario", "DATA_NOT_AVAILABLE"),
                "expected_severity": state.get("expected_severity", "DATA_NOT_AVAILABLE"),
                "actual_severity": agent_decision["final_output"]["severity"],
                "windows_processed": 1,
                "failed_windows": 0,
                "decision_quality_metrics": compute_decision_quality_metrics([record]),
                "finops_metrics": compute_finops_metrics(
                    event_count=len(events),
                    windows_processed=1,
                ),
            }

            silver_key = f"silver/decisions/{run_id}_decision.json"
            gold_key = f"gold/decision_metrics/{run_id}_summary.json"

            put_json_safe(bucket, silver_key, record)
            put_json_safe(bucket, gold_key, summary)

            return {
                "statusCode": 200,
                "run_id": run_id,
                "scenario": state.get("scenario", "DATA_NOT_AVAILABLE"),
                "expected_severity": state.get("expected_severity", "DATA_NOT_AVAILABLE"),
                "actual_severity": agent_decision["final_output"]["severity"],
                "bucket": bucket,
                "silver_key": silver_key,
                "gold_key": gold_key,
                "final_output": agent_decision["final_output"],
            }

        return {
            "statusCode": 400,
            "run_id": run_id,
            "error": f"Unknown step: {step}",
        }

    except Exception as exc:
        error_key = f"logs/errors/{run_id}_error.json"

        error_record = {
            "run_id": run_id,
            "timestamp_utc": utc_now_iso(),
            "step": step,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "input_event": event,
            "state": state,
        }

        put_json_safe(bucket, error_key, error_record)

        return {
            "statusCode": 500,
            "run_id": run_id,
            "step": step,
            "error": str(exc),
            "error_key": error_key,
        }