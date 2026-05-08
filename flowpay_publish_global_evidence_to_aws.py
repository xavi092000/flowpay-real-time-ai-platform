import json
from pathlib import Path
from datetime import datetime, timezone

import boto3


PROJECT_ROOT = Path(__file__).resolve().parent

GLOBAL_EVIDENCE_DIR = PROJECT_ROOT / "outputs" / "global_evidence"
GLOBAL_SUMMARY_FILE = GLOBAL_EVIDENCE_DIR / "flowpay_global_evidence_summary.json"

AWS_REGION = "us-east-1"
S3_BUCKET = "flowpay-data-573b3f0a"  # change si ton bucket a un autre nom
S3_PREFIX = "evidence/global"

CLOUDWATCH_NAMESPACE = "FlowPay"


def load_global_summary() -> dict:
    if not GLOBAL_SUMMARY_FILE.exists():
        raise FileNotFoundError(f"Missing global evidence summary: {GLOBAL_SUMMARY_FILE}")

    with GLOBAL_SUMMARY_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def upload_evidence_to_s3() -> list[str]:
    s3 = boto3.client("s3", region_name=AWS_REGION)
    uploaded = []

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    for file_path in GLOBAL_EVIDENCE_DIR.glob("*"):
        if file_path.is_file():
            key = f"{S3_PREFIX}/{timestamp}/{file_path.name}"
            s3.upload_file(str(file_path), S3_BUCKET, key)
            uploaded.append(f"s3://{S3_BUCKET}/{key}")

    return uploaded


def publish_cloudwatch_metrics(summary: dict) -> None:
    cloudwatch = boto3.client("cloudwatch", region_name=AWS_REGION)

    global_summary = summary["summary"]

    verdict = global_summary.get("verdict")
    passed_layers = float(global_summary.get("passed_layers", 0))
    failed_layers = float(global_summary.get("failed_layers", 0))
    pass_rate = float(global_summary.get("pass_rate", 0.0))

    cloudwatch.put_metric_data(
        Namespace=CLOUDWATCH_NAMESPACE,
        MetricData=[
            {
                "MetricName": "GlobalValidationPass",
                "Value": 1 if verdict == "PASS" else 0,
                "Unit": "Count",
            },
            {
                "MetricName": "GlobalValidationPassedLayers",
                "Value": passed_layers,
                "Unit": "Count",
            },
            {
                "MetricName": "GlobalValidationFailedLayers",
                "Value": failed_layers,
                "Unit": "Count",
            },
            {
                "MetricName": "GlobalValidationPassRate",
                "Value": pass_rate,
                "Unit": "None",
            },
        ],
    )


def main() -> None:
    print("\nFLOWPAY PUBLISH GLOBAL EVIDENCE TO AWS")
    print("=" * 80)

    summary = load_global_summary()

    uploaded_files = upload_evidence_to_s3()
    publish_cloudwatch_metrics(summary)

    output = {
        "status": "PASS",
        "uploaded_files": uploaded_files,
        "cloudwatch_namespace": CLOUDWATCH_NAMESPACE,
        "metrics_published": [
            "GlobalValidationPass",
            "GlobalValidationPassedLayers",
            "GlobalValidationFailedLayers",
            "GlobalValidationPassRate",
        ],
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()