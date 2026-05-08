import json
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "lineage"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


LINEAGE_STEPS = [
    {
        "step": 1,
        "layer": "Ingestion",
        "component": "Event Source",
        "input": "Market events",
        "output": "Raw event payloads",
        "evidence": "Synthetic 30s replay + adversarial events",
    },
    {
        "step": 2,
        "layer": "Data Quality",
        "component": "flowpay_data_quality_layer.py",
        "input": "Raw event payloads",
        "output": "Validated / rejected events",
        "evidence": "outputs/data_quality/flowpay_data_quality_summary.json",
    },
    {
        "step": 3,
        "layer": "Failure Handling",
        "component": "flowpay_failure_replay_layer.py",
        "input": "Validated events",
        "output": "Processed, retried, skipped duplicates, or DLQ",
        "evidence": "outputs/failure_replay/flowpay_failure_replay_summary.json",
    },
    {
        "step": 4,
        "layer": "Risk Engine",
        "component": "flowpay_quant_engine.py",
        "input": "Clean event windows",
        "output": "MRS, severity, recommended action",
        "evidence": "outputs/event_replay_30s/flowpay_30s_event_replay_summary.json",
    },
    {
        "step": 5,
        "layer": "Calibration",
        "component": "flowpay_empirical_mrs_calibration_report.py",
        "input": "Historical multi-asset OHLC data",
        "output": "MRS severity calibration evidence",
        "evidence": "outputs/calibration/flowpay_empirical_mrs_calibration_summary.json",
    },
    {
        "step": 6,
        "layer": "Adversarial Validation",
        "component": "flowpay_adversarial_event_replay.py",
        "input": "Stress, invalid, edge-case event scenarios",
        "output": "Robustness validation results",
        "evidence": "outputs/adversarial_validation/flowpay_adversarial_event_replay_summary.json",
    },
    {
        "step": 7,
        "layer": "RAG Explanation",
        "component": "flowpay_rag_with_quant.py + Qdrant",
        "input": "Quant decision",
        "output": "AI-generated explanation with retrieval confidence",
        "evidence": "outputs/rag_evaluation/flowpay_rag_evaluation_summary.json",
    },
    {
        "step": 8,
        "layer": "Observability",
        "component": "CloudWatch metrics + alarms",
        "input": "Decision metrics",
        "output": "Latency / success / failure / MRS observability",
        "evidence": "CloudWatch namespace FlowPay + alarms",
    },
    {
        "step": 9,
        "layer": "FinOps",
        "component": "flowpay_finops_cost_report.py",
        "input": "Quant + RAG runs",
        "output": "Estimated cost per run",
        "evidence": "outputs/finops/flowpay_finops_cost_summary.json",
    },
]


def check_evidence_exists(path_or_note: str) -> str:
    if path_or_note.startswith("outputs/"):
        evidence_path = PROJECT_ROOT / path_or_note
        return "FOUND" if evidence_path.exists() else "MISSING"

    return "EXTERNAL_OR_MANUAL"


def generate_lineage_report() -> None:
    print("\nFLOWPAY DATA LINEAGE / ARCHITECTURE EVIDENCE")
    print("=" * 80)

    rows = []

    for item in LINEAGE_STEPS:
        evidence_status = check_evidence_exists(item["evidence"])

        row = {
            **item,
            "evidence_status": evidence_status,
        }

        rows.append(row)

        print(
            f"{item['step']}. {item['layer']} | "
            f"{item['component']} | evidence={evidence_status}"
        )

    missing = [row for row in rows if row["evidence_status"] == "MISSING"]

    summary = {
        "validation_type": "data_lineage_architecture_evidence",
        "total_steps": len(rows),
        "evidence_found": sum(row["evidence_status"] == "FOUND" for row in rows),
        "manual_or_external_evidence": sum(
            row["evidence_status"] == "EXTERNAL_OR_MANUAL" for row in rows
        ),
        "missing_evidence": len(missing),
        "verdict": "PASS" if len(missing) == 0 else "FAIL",
    }

    evidence = {
        "summary": summary,
        "lineage_steps": rows,
    }

    with open(OUTPUT_DIR / "flowpay_data_lineage_summary.json", "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)

    pd.DataFrame(rows).to_csv(
        OUTPUT_DIR / "flowpay_data_lineage_results.csv",
        index=False,
    )

    report_lines = [
        "# FlowPay Data Lineage / Architecture Evidence",
        "",
        "## Purpose",
        "",
        "This report documents the end-to-end lineage of the FlowPay real-time financial intelligence pipeline.",
        "",
        "## Lineage",
        "",
    ]

    for row in rows:
        report_lines.extend(
            [
                f"### {row['step']}. {row['layer']}",
                "",
                f"- Component: `{row['component']}`",
                f"- Input: {row['input']}",
                f"- Output: {row['output']}",
                f"- Evidence: `{row['evidence']}`",
                f"- Evidence status: **{row['evidence_status']}**",
                "",
            ]
        )

    report_lines.extend(
        [
            "## Summary",
            "",
            "```json",
            json.dumps(summary, indent=2),
            "```",
        ]
    )

    (OUTPUT_DIR / "flowpay_data_lineage_report.md").write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )

    print("\nFINAL SUMMARY")
    print(json.dumps(summary, indent=2))

    print("\nSaved:")
    print(OUTPUT_DIR / "flowpay_data_lineage_summary.json")
    print(OUTPUT_DIR / "flowpay_data_lineage_results.csv")
    print(OUTPUT_DIR / "flowpay_data_lineage_report.md")


if __name__ == "__main__":
    generate_lineage_report()