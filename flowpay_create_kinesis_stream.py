import time
import boto3


AWS_REGION = "us-east-1"
STREAM_NAME = "flowpay-market-events"
SHARD_COUNT = 1


def stream_exists(kinesis, stream_name: str) -> bool:
    try:
        kinesis.describe_stream_summary(StreamName=stream_name)
        return True
    except kinesis.exceptions.ResourceNotFoundException:
        return False


def wait_until_active(kinesis, stream_name: str) -> None:
    print(f"Waiting for stream to become ACTIVE: {stream_name}")

    while True:
        response = kinesis.describe_stream_summary(StreamName=stream_name)
        status = response["StreamDescriptionSummary"]["StreamStatus"]

        print(f"Current status: {status}")

        if status == "ACTIVE":
            return

        time.sleep(5)


def main() -> None:
    print("\nFLOWPAY KINESIS STREAM CREATION")
    print("=" * 80)

    kinesis = boto3.client("kinesis", region_name=AWS_REGION)

    if stream_exists(kinesis, STREAM_NAME):
        print(f"Stream already exists: {STREAM_NAME}")
    else:
        print(f"Creating stream: {STREAM_NAME}")
        kinesis.create_stream(
            StreamName=STREAM_NAME,
            ShardCount=SHARD_COUNT,
        )

    wait_until_active(kinesis, STREAM_NAME)

    response = kinesis.describe_stream_summary(StreamName=STREAM_NAME)
    summary = response["StreamDescriptionSummary"]

    print("\nRESULT: PASS")
    print(f"Stream Name: {summary['StreamName']}")
    print(f"Stream ARN: {summary['StreamARN']}")
    print(f"Status: {summary['StreamStatus']}")
    print(f"Open Shards: {summary['OpenShardCount']}")


if __name__ == "__main__":
    main()