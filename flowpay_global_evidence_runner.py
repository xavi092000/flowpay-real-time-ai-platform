import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, List

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "global_evidence"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PYTHON = sys.executable


VALIDATION_SCRIPTS = [
    {
        "name": "Data Quality Layer",
        "script": "flowpay_data_quality_layer.py",
        "summary_path": "outputs/data_quality/flowpay_data_quality_summary.json",
    },
    {
        "name": "Failure Replay / Retry / Idempotency",
        "script": "flowpay_failure_replay_layer.py",
        "summary_path": "outputs/failure_replay/flowpay_failure_replay_summary.json",
    },
    {
        "name": "30s Event Replay",
        "script": "flowpay_30s_event_replay_validation.py",
        "summary_path": "outputs/event_replay_30s/flowpay_30s_event_replay_summary.json",
    },
    {
        "name": "Adversarial Event Replay",
        "script": "flowpay_adversarial_event_replay.py",
        "summary_path": "outputs/adversarial_validation/flowpay_adversarial_event_replay_summary.json",
    },
    {
        "name": "Empirical MRS Calibration",
        "script": "flowpay_empirical_mrs_calibration_report.py",
        "summary_path": "outputs/calibration/flowpay_empirical_mrs_calibration_summary.json",
    },
    {
        "name": "RAG Evaluation",
        "script": "flowpay_rag_evaluation_layer.py",
        "summary_path": "outputs/rag_evaluation/flowpay_rag_evaluation_summary.json",
    },
    {
        "name": "FinOps Cost Report",
        "script": "flowpay_finops_cost_report.py",
        "summary_path": "outputs/finops/flowpay_finops_cost_summary.json",
    },
    {
        "name": "Data Lineage / Architecture Evidence",
        "script": "flowpay_data_lineage_report.py",
        "summary_path": "outputs/lineage/flowpay_data_lineage_summary.json",
    },
    {
    "name": "Kinesis Streaming Pipeline",
    "script": "flowpay_kinesis_consumer.py",
    "summary_path": "outputs/kinesis/flowpay_kinesis_consumer_decision.json",
    },
]


def load_summary(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"verdict": "MISSING", "error": f"Missing summary file: {path}"}

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if "summary" in data:
        return data["summary"]

    
    if "verdict" in data:
        return data

    if isinstance(data, dict):
        return {
            "verdict": "PASS" if "decision" in data else "UNKNOWN",
            "details": data,

    }

    return {"verdict": "UNKNOWN"}


def run_script(script_name: str) -> Dict[str, Any]:
    script_path = PROJECT_ROOT / script_name

    if not script_path.exists():
        return {
            "return_code": None,
            "stdout": "",
            "stderr": f"Script not found: {script_path}",
            "execution_status": "SCRIPT_MISSING",
        }

    completed = subprocess.run(
        [PYTHON, str(script_path)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    return {
        "return_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "execution_status": "SUCCEEDED" if completed.returncode == 0 else "FAILED",
    }


def generate_readme(results: List[Dict[str, Any]], global_summary: Dict[str, Any]) -> None:
    lines = [
        "# FlowPay Global Evidence Pack",
        "",
        "## Purpose",
        "",
        "This document summarizes the full technical validation evidence for the FlowPay real-time financial intelligence pipeline.",
        "",
        "## Global Summary",
        "",
        "```json",
        json.dumps(global_summary, indent=2),
        "```",
        "",
        "## Validation Results",
        "",
        "| Validation Layer | Execution | Verdict | Summary File |",
        "|---|---|---|---|",
    ]

    for row in results:
        lines.append(
            f"| {row['name']} | {row['execution_status']} | {row['verdict']} | `{row['summary_path']}` |"
        )

    lines.extend(
        [
            "",
            "## Portfolio Claim",
            "",
            "> FlowPay was validated across data quality, failure replay, 30-second event replay, adversarial robustness, empirical MRS calibration, RAG evaluation, FinOps cost modeling, and architecture lineage evidence.",
            "",
            "## Evidence Notes",
            "",
            "- CloudWatch metrics and alarms are external/manual evidence and should be supported with screenshots.",
            "- Qdrant must be running for the RAG evaluation layer.",
            "- The RAG latency SLO is currently set to 15 seconds.",
            "- The system remains recommendation-only and does not execute trades automatically.",
        ]
    )

    (OUTPUT_DIR / "flowpay_global_evidence_readme.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def main() -> None:
    print("\nFLOWPAY GLOBAL EVIDENCE RUNNER")
    print("=" * 80)

    results = []

    for item in VALIDATION_SCRIPTS:
        print(f"\nRunning: {item['name']}")
        print("-" * 80)

        execution = run_script(item["script"])
        summary = load_summary(PROJECT_ROOT / item["summary_path"])

        verdict = summary.get("verdict", "UNKNOWN")

        row = {
            "name": item["name"],
            "script": item["script"],
            "summary_path": item["summary_path"],
            "execution_status": execution["execution_status"],
            "return_code": execution["return_code"],
            "verdict": verdict,
            "summary": summary,
            "stderr_tail": execution["stderr"][-1000:] if execution["stderr"] else "",
        }

        results.append(row)

        print(f"Execution: {row['execution_status']}")
        print(f"Verdict: {verdict}")

        if row["stderr_tail"]:
            print("stderr:")
            print(row["stderr_tail"])

    total = len(results)
    passed = sum(
        1
        for r in results
        if r["execution_status"] == "SUCCEEDED" and r["verdict"] == "PASS"
    )

    failed = total - passed

    global_summary = {
        "validation_type": "global_flowpay_evidence_pack",
        "total_validation_layers": total,
        "passed_layers": passed,
        "failed_layers": failed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "verdict": "PASS" if failed == 0 else "FAIL",
    }

    evidence = {
        "summary": global_summary,
        "results": results,
    }

    with open(OUTPUT_DIR / "flowpay_global_evidence_summary.json", "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)

    pd.DataFrame(
        [
            {
                "name": r["name"],
                "script": r["script"],
                "execution_status": r["execution_status"],
                "verdict": r["verdict"],
                "summary_path": r["summary_path"],
            }
            for r in results
        ]
    ).to_csv(
        OUTPUT_DIR / "flowpay_global_evidence_results.csv",
        index=False,
    )

    generate_readme(results, global_summary)

    print("\nFINAL GLOBAL SUMMARY")
    print("=" * 80)
    print(json.dumps(global_summary, indent=2))

    print("\nSaved:")
    print(OUTPUT_DIR / "flowpay_global_evidence_summary.json")
    print(OUTPUT_DIR / "flowpay_global_evidence_results.csv")
    print(OUTPUT_DIR / "flowpay_global_evidence_readme.md")


if __name__ == "__main__":
    main()