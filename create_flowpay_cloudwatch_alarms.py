import boto3
from botocore.exceptions import BotoCoreError, ClientError


REGION = "us-east-1"
NAMESPACE = "FlowPay"

cloudwatch = boto3.client("cloudwatch", region_name=REGION)


def create_latency_alarm() -> None:
    cloudwatch.put_metric_alarm(
        AlarmName="flowpay-decision-latency-slo-breach",
        AlarmDescription="Triggers when FlowPay decision latency exceeds the 5 second SLO.",
        Namespace=NAMESPACE,
        MetricName="DecisionLatency",
        Dimensions=[],
        Statistic="Maximum",
        Period=60,
        EvaluationPeriods=1,
        DatapointsToAlarm=1,
        Threshold=5.0,
        ComparisonOperator="GreaterThanThreshold",
        TreatMissingData="notBreaching",
        ActionsEnabled=False,
    )


def create_failure_alarm() -> None:
    cloudwatch.put_metric_alarm(
        AlarmName="flowpay-decision-failure-detected",
        AlarmDescription="Triggers when FlowPay reports at least one failed decision.",
        Namespace=NAMESPACE,
        MetricName="DecisionFailure",
        Dimensions=[],
        Statistic="Sum",
        Period=60,
        EvaluationPeriods=1,
        DatapointsToAlarm=1,
        Threshold=1.0,
        ComparisonOperator="GreaterThanOrEqualToThreshold",
        TreatMissingData="notBreaching",
        ActionsEnabled=False,
    )


def main() -> None:
    print("\nFLOWPAY CLOUDWATCH ALARM CREATION")
    print("=" * 80)

    try:
        create_latency_alarm()
        print("Created alarm: flowpay-decision-latency-slo-breach")

        create_failure_alarm()
        print("Created alarm: flowpay-decision-failure-detected")

        print("\nRESULT: PASS")

    except (ClientError, BotoCoreError) as exc:
        print(f"\nRESULT: FAIL")
        print(f"Error: {exc}")


if __name__ == "__main__":
    main()