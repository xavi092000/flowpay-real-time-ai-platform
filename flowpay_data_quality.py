from typing import Any, Dict, List, Tuple


REQUIRED_FIELDS = {
    "event_id": str,
    "timestamp": str,
    "symbol": str,
    "side": str,
    "price": (int, float),
    "volume": (int, float),
    "bid": (int, float),
    "ask": (int, float),
    "bid_depth": (int, float),
    "ask_depth": (int, float),
}


VALID_SIDES = {"buy", "sell"}


def validate_event_schema(event: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors = []

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in event:
            errors.append(f"Missing required field: {field}")
            continue

        if not isinstance(event[field], expected_type):
            errors.append(
                f"Invalid type for {field}: expected {expected_type}, "
                f"got {type(event[field]).__name__}"
            )

    return len(errors) == 0, errors


def validate_event_values(event: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors = []

    side = event.get("side")
    if side is not None and str(side).lower() not in VALID_SIDES:
        errors.append(f"Invalid side: {side}")

    price = event.get("price")
    if isinstance(price, (int, float)) and price <= 0:
        errors.append(f"Invalid price: {price}")

    volume = event.get("volume")
    if isinstance(volume, (int, float)) and volume <= 0:
        errors.append(f"Invalid volume: {volume}")

    bid = event.get("bid")
    ask = event.get("ask")

    if isinstance(bid, (int, float)) and bid <= 0:
        errors.append(f"Invalid bid: {bid}")

    if isinstance(ask, (int, float)) and ask <= 0:
        errors.append(f"Invalid ask: {ask}")

    if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and bid >= ask:
        errors.append(f"Invalid market spread: bid {bid} must be lower than ask {ask}")

    bid_depth = event.get("bid_depth")
    ask_depth = event.get("ask_depth")

    if isinstance(bid_depth, (int, float)) and bid_depth <= 0:
        errors.append(f"Invalid bid_depth: {bid_depth}")

    if isinstance(ask_depth, (int, float)) and ask_depth <= 0:
        errors.append(f"Invalid ask_depth: {ask_depth}")

    return len(errors) == 0, errors


def validate_event(event: Dict[str, Any]) -> Dict[str, Any]:
    schema_ok, schema_errors = validate_event_schema(event)
    value_ok, value_errors = validate_event_values(event)

    errors = schema_errors + value_errors

    return {
        "is_valid": schema_ok and value_ok,
        "errors": errors,
        "event_id": event.get("event_id", "UNKNOWN"),
    }


def validate_events(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_events = len(events)
    invalid_events = []

    for event in events:
        result = validate_event(event)
        if not result["is_valid"]:
            invalid_events.append(result)

    valid_events_count = total_events - len(invalid_events)
    quality_score = valid_events_count / total_events if total_events > 0 else 0

    return {
        "total_events": total_events,
        "valid_events": valid_events_count,
        "invalid_events": len(invalid_events),
        "quality_score": round(quality_score, 4),
        "invalid_event_details": invalid_events,
        "passed": len(invalid_events) == 0,
    }