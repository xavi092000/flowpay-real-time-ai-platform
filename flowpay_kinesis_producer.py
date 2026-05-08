import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import boto3


AWS_REGION = "us-east-1"
STREAM_NAME = "flowpay-market-events"


def make_event(index: int) -> Dict[str, Any]:
    base_price = 67000 - (index * 25)

    side = "sell" if index % 3 != 0 else "buy"

    return {
        "event_id": f"kinesis_{uuid.uuid4()}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": "BTC-USD",
        "side": side,
        "price": base_price,
        "volume": 1.0 + (index * 0.2),
        "bid": base_price - 10,
        "ask": base_price + 10,
        "bid_depth": max(50_000, 600_000 - (index * 15_000)),
        "ask_depth": 600_000 + (index * 20_000),
    }


def publish_event(kinesis, event: Dict[str, Any]) -> Dict[str, Any]:
    response = kinesis.put_record(
        StreamName=STREAM_NAME,
        Data=json.dumps(event).encode("utf-8"),
        PartitionKey=event["symbol"],
    )

    return {
        "event_id": event["event_id"],
        "sequence_number": response["SequenceNumber"],
        "shard_id": response["ShardId"],
    }


def main() -> None:
    print("\nFLOWPAY KINESIS PRODUCER")
    print("=" * 80)

    kinesis = boto3.client("kinesis", region_name=AWS_REGION)

    published: List[Dict[str, Any]] = []

    for i in range(10):
        event = make_event(i)
        result = publish_event(kinesis, event)
        published.append(result)

        print(
            f"Published {i + 1}/10 | "
            f"event_id={result['event_id']} | "
            f"shard={result['shard_id']}"
        )

        time.sleep(0.5)

    print("\nRESULT: PASS")
    print(json.dumps(
        {
            "stream": STREAM_NAME,
            "events_published": len(published),
            "published": published,
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()