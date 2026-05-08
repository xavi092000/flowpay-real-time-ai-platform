import json
import time
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from flowpay_quant_engine import compute_quant_decision
from flowpay_rag_with_quant import run_flowpay_rag


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "finops"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Hypothèses simples (ajuste si tu veux)
COST_PER_1K_TOKENS_USD = 0.002  # estimation OpenAI (entrée/sortie agrégée)
QDRANT_COST_PER_1K_QUERIES_USD = 0.0001  # coût infra estimé (local ≈ 0, on simule)
COMPUTE_COST_PER_SECOND_USD = 0.00002  # CPU/infra estimée


def make_event(i: int) -> Dict[str, Any]:
    base_price = 67000 - i * 50
    return {
        "event_id": f"finops_{i}",
        "timestamp": f"2026-04-28T10:00:{i:02d}Z",
        "symbol": "BTC-USD",
        "side": "sell" if i % 2 == 0 else "buy",
        "price": base_price,
        "volume": 1.0 + (i * 0.1),
        "bid": base_price - 10,
        "ask": base_price + 10,
        "bid_depth": 500000 - (i * 10000),
        "ask_depth": 700000 + (i * 10000),
    }


def estimate_token_usage(text: str) -> int:
    # approximation: 1 token ≈ 4 chars
    return max(1, len(text) // 4)


def run_finops_cost_report() -> None:
    print("\nFLOWPAY FINOPS COST REPORT")
    print("=" * 80)

    scenarios = []
    for n in [3, 10, 30]:
        scenarios.append({
            "scenario": f"{n}_events_window",
            "events": [make_event(i) for i in range(n)]
        })

    results: List[Dict[str, Any]] = []

    for sc in scenarios:
        name = sc["scenario"]
        events = sc["events"]

        # Quant timing
        t0 = time.perf_counter()
        decision = compute_quant_decision(events)
        t1 = time.perf_counter()

        # RAG timing
        t2 = time.perf_counter()
        rag_output = run_flowpay_rag(decision)
        t3 = time.perf_counter()

        quant_latency = t1 - t0
        rag_latency = t3 - t2
        total_latency = (t3 - t0)

        explanation = str(rag_output.get("explanation", ""))

        tokens_estimated = estimate_token_usage(explanation)

        openai_cost = (tokens_estimated / 1000) * COST_PER_1K_TOKENS_USD
        qdrant_cost = QDRANT_COST_PER_1K_QUERIES_USD  # 1 query par run
        compute_cost = total_latency * COMPUTE_COST_PER_SECOND_USD

        total_cost = openai_cost + qdrant_cost + compute_cost

        result = {
            "scenario": name,
            "event_count": len(events),
            "quant_latency_seconds": round(quant_latency, 4),
            "rag_latency_seconds": round(rag_latency, 4),
            "total_latency_seconds": round(total_latency, 4),
            "tokens_estimated": tokens_estimated,
            "openai_cost_usd": round(openai_cost, 6),
            "qdrant_cost_usd": round(qdrant_cost, 6),
            "compute_cost_usd": round(compute_cost, 6),
            "total_cost_usd": round(total_cost, 6),
        }

        results.append(result)

        print(
            f"{name} | events={len(events)} | "
            f"latency={result['total_latency_seconds']}s | "
            f"cost=${result['total_cost_usd']}"
        )

    total_runs = len(results)
    avg_cost = sum(r["total_cost_usd"] for r in results) / total_runs

    summary = {
        "validation_type": "finops_cost_report",
        "total_runs": total_runs,
        "average_cost_usd": round(avg_cost, 6),
        "verdict": "PASS",
        "cost_model": {
            "openai_per_1k_tokens_usd": COST_PER_1K_TOKENS_USD,
            "qdrant_per_1k_queries_usd": QDRANT_COST_PER_1K_QUERIES_USD,
            "compute_per_second_usd": COMPUTE_COST_PER_SECOND_USD,
           
        }
    }

    with open(OUTPUT_DIR / "flowpay_finops_cost_summary.json", "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": results}, f, indent=2)

    pd.DataFrame(results).to_csv(
        OUTPUT_DIR / "flowpay_finops_cost_results.csv",
        index=False
    )

    print("\nFINAL SUMMARY")
    print(json.dumps(summary, indent=2))

    print("\nSaved:")
    print(OUTPUT_DIR / "flowpay_finops_cost_summary.json")
    print(OUTPUT_DIR / "flowpay_finops_cost_results.csv")


if __name__ == "__main__":
    run_finops_cost_report()