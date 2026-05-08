import json
from pathlib import Path
from typing import Any

from flowpay_quant_engine import compute_quant_decision
from flowpay_rag_with_quant import run_flowpay_rag


PROJECT_ROOT = Path(__file__).resolve().parent
REPLAY_FILE = PROJECT_ROOT / "data" / "flowpay_replay_events.json"


def load_replay_events(path: Path = REPLAY_FILE) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Replay file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        events = json.load(file)

    if not isinstance(events, list):
        raise ValueError("Replay file must contain a JSON array of events.")

    return events


def run_replay() -> None:
    print("\nFLOWPAY REALISTIC REPLAY — QUANT + RAG")
    print("=" * 80)

    events = load_replay_events()

    decision = compute_quant_decision(
        events=events,
        previous_mrs_values=[22.5, 28.1, 31.4],
    )

    print("\nQUANT DECISION")
    print("-" * 80)
    print(json.dumps(decision, indent=2))

    rag_output = run_flowpay_rag(decision)

    print("\nRAG EXPLANATION")
    print("-" * 80)
    print(rag_output["explanation"])

    print("\nRAG CONFIDENCE")
    print("-" * 80)
    print(json.dumps(rag_output["retrieval_confidence"], indent=2))

    print("\nCOST")
    print("-" * 80)
    print(json.dumps(rag_output["cost"], indent=2))

    print("\nLATENCY")
    print("-" * 80)
    print(json.dumps(rag_output["latency"], indent=2))

    print("\nREPLAY COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    run_replay()