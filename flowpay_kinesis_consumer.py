import base64
import json
import time
from pathlib import Path
from typing import Any, Dict, List

import boto3
import pandas as pd

from flowpay_quant_engine import compute_quant_decision


AWS_REGION = "us-east-1"
STREAM_NAME = "flowpay-market-events"
WINDOW_SIZE = 10

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "kinesis"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_shard_iterator(kinesis) -> str:
    stream = kinesis.describe_stream(StreamName=STREAM_NAME)
    shard_id = stream["StreamDescription"]["Shards"][0]["ShardId"]

    response = kinesis.get_shard_iterator(
        StreamName=STREAM_NAME,
        ShardId=shard_id,
        ShardIteratorType="TRIM_HORIZON",
    )

    return response["ShardIterator"]


def decode_record(record: Dict[str, Any]) -> Dict[str, Any]:
    data = record["Data"]

    if isinstance(data, bytes):
        return json.loads(data.decode("utf-8"))

    decoded = base64.b64decode(data).decode("utf-8")
    return json.loads(decoded)


def read_records(kinesis, shard_iterator: str, max_records: int = 10) -> List[Dict[str, Any]]:
    response = kinesis.get_records(
        ShardIterator=shard_iterator,
        Limit=max_records,
    )

    records = [decode_record(record) for record in response["Records"]]

    return records


def run_kinesis_consumer() -> None:
    print("\nFLOWPAY KINESIS CONSUMER")
    print("=" * 80)

    kinesis = boto3.client("kinesis", region_name=AWS_REGION)

    shard_iterator = get_shard_iterator(kinesis)

    print(f"Reading from stream: {STREAM_NAME}")

    events = []

    for _ in range(5):
        batch = read_records(kinesis, shard_iterator, max_records=WINDOW_SIZE)

        if batch:
            events.extend(batch)
            break

        print("No records yet. Waiting...")
        time.sleep(2)

    if not events:
        raise RuntimeError("No Kinesis records found. Run producer first.")

    events = events[:WINDOW_SIZE]

    decision = compute_quant_decision(events)

    output = {
        "source": "kinesis",
        "stream": STREAM_NAME,
        "events_consumed": len(events),
        "event_ids": [event["event_id"] for event in events],
        "decision": {
            "mrs": decision.get("market_risk_score"),
            "severity": decision.get("severity"),
            "dominant_problem": decision.get("dominant_problem"),
            "recommended_action": decision.get("recommended_action"),
            "governance_status": decision.get("governance_status"),
        },
    }

    output_file = OUTPUT_DIR / "flowpay_kinesis_consumer_decision.json"

    with output_file.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    pd.DataFrame(events).to_csv(
        OUTPUT_DIR / "flowpay_kinesis_consumed_events.csv",
        index=False,
    )

    print("\nRESULT: PASS")
    print(json.dumps(output, indent=2))

    print("\nSaved:")
    print(output_file)
    print(OUTPUT_DIR / "flowpay_kinesis_consumed_events.csv")


if __name__ == "__main__":
    run_kinesis_consumer()