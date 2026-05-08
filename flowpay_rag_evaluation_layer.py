import json
import time
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from flowpay_quant_engine import compute_quant_decision
from flowpay_rag_with_quant import run_flowpay_rag


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "rag_evaluation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SLO_LATENCY_SECONDS = 20.0
MIN_RETRIEVAL_CONFIDENCE = 0.50


def make_event(
    event_id: str,
    timestamp: str,
    side: str,
    price: float,
    volume: float,
    bid: float,
    ask: float,
    bid_depth: float,
    ask_depth: float,
    symbol: str = "BTC-USD",
) -> Dict[str, Any]:
    return {
        "event_id": event_id,
        "timestamp": timestamp,
        "symbol": symbol,
        "side": side,
        "price": price,
        "volume": volume,
        "bid": bid,
        "ask": ask,
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
    }


def build_rag_eval_scenarios() -> List[Dict[str, Any]]:
    return [
        {
            "scenario": "normal_market_explanation",
            "events": [
                make_event("rag_001", "2026-04-28T10:00:00Z", "buy", 67000, 1.0, 66990, 67010, 600000, 610000),
                make_event("rag_002", "2026-04-28T10:00:10Z", "buy", 67010, 0.8, 67000, 67020, 605000, 608000),
            ],
            "required_terms": ["Normal", "monitor", "risk"],
        },
        {
            "scenario": "defensive_liquidity_explanation",
            "events": [
                make_event("rag_003", "2026-04-28T10:01:00Z", "sell", 67000, 5.0, 66800, 67200, 300000, 700000),
                make_event("rag_004", "2026-04-28T10:01:10Z", "sell", 66200, 8.0, 65900, 66500, 70000, 900000),
            ],
            "required_terms": ["Defensive", "liquidity", "risk"],
        },
        {
            "scenario": "critical_flash_crash_explanation",
            "events": [
                make_event("rag_005", "2026-04-28T10:02:00Z", "sell", 65000, 15.0, 64500, 65500, 250000, 800000),
                make_event("rag_006", "2026-04-28T10:02:10Z", "sell", 59000, 30.0, 58100, 59900, 50000, 900000),
            ],
            "required_terms": ["Critical", "risk"],
        },
    ]


def safe_get_confidence(rag_output: Dict[str, Any]) -> float:
    confidence = rag_output.get("retrieval_confidence", {})

    if isinstance(confidence, dict):
        for key in ["score", "confidence", "retrieval_score", "avg_score"]:
            value = confidence.get(key)
            if isinstance(value, (int, float)):
                return float(value)

    return 1.0


def validate_explanation(
    scenario: Dict[str, Any],
    decision: Dict[str, Any],
    rag_output: Dict[str, Any],
    latency_seconds: float,
) -> Dict[str, Any]:
    errors = []

    explanation = str(rag_output.get("explanation", "")).strip()
    confidence = safe_get_confidence(rag_output)

    if not explanation:
        errors.append("empty_explanation")

    if "I don't have enough information" in explanation:
        errors.append("rag_fallback_triggered")

    for term in scenario["required_terms"]:
        if term.lower() not in explanation.lower():
            errors.append(f"missing_required_term: {term}")

    severity = decision.get("severity")
    if severity and severity.lower() not in explanation.lower():
        errors.append(f"severity_not_mentioned: {severity}")

    if confidence < MIN_RETRIEVAL_CONFIDENCE:
        errors.append(f"low_retrieval_confidence: {confidence}")

    if latency_seconds > SLO_LATENCY_SECONDS:
        errors.append(f"latency_slo_breach: {latency_seconds}")

    return {
        "explanation": explanation,
        "retrieval_confidence": confidence,
        "errors": errors,
        "passed": len(errors) == 0,
    }


def run_rag_evaluation() -> None:
    print("\nFLOWPAY RAG EVALUATION LAYER")
    print("=" * 80)

    scenarios = build_rag_eval_scenarios()
    results = []

    for scenario in scenarios:
        name = scenario["scenario"]

        decision = compute_quant_decision(scenario["events"])

        start = time.perf_counter()
        rag_output = run_flowpay_rag(decision)
        latency_seconds = time.perf_counter() - start

        validation = validate_explanation(
            scenario=scenario,
            decision=decision,
            rag_output=rag_output,
            latency_seconds=latency_seconds,
        )

        result = {
            "scenario": name,
            "severity": decision.get("severity"),
            "mrs": decision.get("market_risk_score"),
            "action": decision.get("recommended_action"),
            "retrieval_confidence": validation["retrieval_confidence"],
            "latency_seconds": round(latency_seconds, 4),
            "errors": validation["errors"],
            "test_passed": validation["passed"],
        }

        results.append(result)

        print(
            f"{'PASS' if validation['passed'] else 'FAIL'} | "
            f"{name} | severity={result['severity']} | "
            f"confidence={result['retrieval_confidence']} | "
            f"latency={result['latency_seconds']}s"
        )

    total = len(results)
    passed = sum(1 for result in results if result["test_passed"])

    summary = {
        "validation_type": "rag_evaluation_layer",
        "total_tests": total,
        "passed_tests": passed,
        "failed_tests": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "minimum_retrieval_confidence": MIN_RETRIEVAL_CONFIDENCE,
        "slo_latency_seconds": SLO_LATENCY_SECONDS,
        "verdict": "PASS" if passed == total else "FAIL",
    }

    evidence = {
        "summary": summary,
        "results": results,
    }

    with open(OUTPUT_DIR / "flowpay_rag_evaluation_summary.json", "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)

    pd.DataFrame(results).to_csv(
        OUTPUT_DIR / "flowpay_rag_evaluation_results.csv",
        index=False,
    )

    print("\nFINAL SUMMARY")
    print(json.dumps(summary, indent=2))

    print("\nSaved:")
    print(OUTPUT_DIR / "flowpay_rag_evaluation_summary.json")
    print(OUTPUT_DIR / "flowpay_rag_evaluation_results.csv")


if __name__ == "__main__":
    run_rag_evaluation()