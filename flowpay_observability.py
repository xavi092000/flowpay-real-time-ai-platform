from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError


REGION = "us-east-1"
NAMESPACE = "FlowPay"

cloudwatch = boto3.client("cloudwatch", region_name=REGION)


def publish_metric(
    metric_name: str,
    value: float,
    unit: str = "Count",
    dimensions: Optional[list[dict[str, str]]] = None,
) -> bool:
    try:
        cloudwatch.put_metric_data(
            Namespace=NAMESPACE,
            MetricData=[
                {
                    "MetricName": metric_name,
                    "Timestamp": datetime.now(timezone.utc),
                    "Value": value,
                    "Unit": unit,
                    "Dimensions": dimensions or [],
                }
            ],
        )
        return True

    except (ClientError, BotoCoreError) as exc:
        print(f"CloudWatch metric publish failed: {exc}")
        return False


def publish_decision_metrics(
    scenario: str,
    latency_seconds: Optional[float],
    success: bool,
    mrs: Optional[float],
) -> dict:
    dimensions = [{"Name": "Scenario", "Value": scenario}]

    results = {
        "DecisionLatency": False,
        "DecisionSuccess": False,
        "DecisionFailure": False,
        "MRSValue": False,
    }

    if latency_seconds is not None:
        results["DecisionLatency"] = publish_metric(
            metric_name="DecisionLatency",
            value=float(latency_seconds),
            unit="Seconds",
            dimensions=dimensions,
        )

    results["DecisionSuccess"] = publish_metric(
        metric_name="DecisionSuccess",
        value=1.0 if success else 0.0,
        unit="Count",
        dimensions=dimensions,
    )

    results["DecisionFailure"] = publish_metric(
        metric_name="DecisionFailure",
        value=0.0 if success else 1.0,
        unit="Count",
        dimensions=dimensions,
    )

    if mrs is not None:
        results["MRSValue"] = publish_metric(
            metric_name="MRSValue",
            value=float(mrs),
            unit="None",
            dimensions=dimensions,
        )

    return results