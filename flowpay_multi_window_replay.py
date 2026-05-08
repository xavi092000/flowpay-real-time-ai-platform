import json
from pathlib import Path
from typing import Any
from datetime import datetime, timedelta, timezone

from flowpay_quant_engine import compute_quant_decision
from flowpay_real_quant_rag import run_flowpay_rag
from flowpay_decision_agents import run_decision_agents
from flowpay_decision_metrics import compute_decision_quality_metrics


PROJECT_ROOT = Path(__file__).resolve().parent
REPLAY_FILE = PROJECT_ROOT / "data" / "flowpay_replay_events.json"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "decisions"
SUMMARY_DIR = PROJECT_ROOT / "outputs"

WINDOW_SECONDS = 30


def parse_time(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def load_events() -> list[dict[str, Any]]:
    if not REPLAY_FILE.exists():
        raise FileNotFoundError(f"Replay file not found: {REPLAY_FILE}")

    with REPLAY_FILE.open("r", encoding="utf-8") as file:
        events = json.load(file)

    if not isinstance(events, list):
        raise ValueError("Replay file must contain a JSON list of events.")

    if not events:
        raise ValueError("Replay file contains no events.")

    return events


def split_windows(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    events = sorted(events, key=lambda event: event["timestamp"])

    windows: list[list[dict[str, Any]]] = []
    current_window: list[dict[str, Any]] = []

    start_time = parse_time(events[0]["timestamp"])
    window_end = start_time + timedelta(seconds=WINDOW_SECONDS)

    for event in events:
        event_time = parse_time(event["timestamp"])

        if event_time <= window_end:
            current_window.append(event)
        else:
            windows.append(current_window)
            current_window = [event]
            start_time = event_time
            window_end = start_time + timedelta(seconds=WINDOW_SECONDS)

    if current_window:
        windows.append(current_window)

    return windows


def save_json(file_path: Path, record: dict[str, Any]) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with file_path.open("w", encoding="utf-8") as file:
        json.dump(record, file, indent=2, ensure_ascii=False)


def save_decision(run_id: str, index: int, record: dict[str, Any]) -> Path:
    file_path = OUTPUT_DIR / f"{run_id}_window_{index + 1}.json"
    save_json(file_path, record)
    return file_path


def run_pipeline() -> None:
    print("\nFLOWPAY MULTI-WINDOW REPLAY")
    print("=" * 80)

    events = load_events()
    windows = split_windows(events)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    previous_mrs_values = [22.5, 28.1, 31.4]

    summary: dict[str, Any] = {
        "run_id": run_id,
        "replay_file": str(REPLAY_FILE),
        "window_seconds": WINDOW_SECONDS,
        "events_loaded": len(events),
        "windows_processed": 0,
        "normal": 0,
        "guarded": 0,
        "defensive": 0,
        "critical": 0,
        "failed_windows": 0,
    }

    # 🔥 Nouveau : stockage des décisions pour metrics
    successful_records: list[dict[str, Any]] = []

    for index, window in enumerate(windows):
        print(f"\n--- Window {index + 1} ---")

        try:
            # 1. Quant Engine
            decision = compute_quant_decision(
                events=window,
                previous_mrs_values=previous_mrs_values,
            )

            # 2. Decision Agents
            agent_decision = run_decision_agents(
                events_window=window,
                quant_decision=decision,
            )

            # 3. Decision Intelligence Report (RAG)
            rag = run_flowpay_rag(
                agent_decision["agents"]["rag_context"]["facts_for_rag"]
            )

            severity = str(decision["severity"]).lower()

            if severity in summary:
                summary[severity] += 1

            summary["windows_processed"] += 1

            # 4. Record final
            record = {
                "run_id": run_id,
                "window_index": index + 1,
                "event_count": len(window),
                "quant_decision": decision,
                "agent_decision": agent_decision,
                "decision_intelligence_report": rag,
            }

            # 🔥 Ajout pour metrics
            successful_records.append(record)

            output_file = save_decision(run_id, index, record)

            previous_mrs_values.append(float(decision["market_risk_score"]))

            final_output = agent_decision["final_output"]

            print(
                f"MRS: {final_output['mrs']} "
                f"| Severity: {final_output['severity']} "
                f"| Bundle: {final_output['action_bundle']} "
                f"| Human review: {final_output['human_review_required']}"
            )
            print(f"Saved: {output_file}")

        except Exception as exc:
            summary["failed_windows"] += 1

            error_record = {
                "run_id": run_id,
                "window_index": index + 1,
                "event_count": len(window),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "events": window,
            }

            error_file = OUTPUT_DIR / f"{run_id}_window_{index + 1}_ERROR.json"
            save_json(error_file, error_record)

            print(f"ERROR in window {index + 1}: {type(exc).__name__}: {exc}")
            print(f"Error saved: {error_file}")

    # 🔥 Ajout des metrics
    summary["decision_quality_metrics"] = compute_decision_quality_metrics(successful_records)

    print("\n=== RUN SUMMARY ===")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    summary_file = SUMMARY_DIR / f"{run_id}_summary.json"
    save_json(summary_file, summary)

    print(f"\nSummary saved: {summary_file}")
    print("=" * 80)


if __name__ == "__main__":
    run_pipeline()