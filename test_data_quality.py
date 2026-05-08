from flowpay_data_quality import validate_events


valid_events = [
    {
        "event_id": "evt_001",
        "timestamp": "2026-04-29T14:00:00Z",
        "symbol": "BTC-USD",
        "side": "buy",
        "price": 65000.0,
        "quantity": 1.2,
        "spread_bps": 12.5,
        "latency_ms": 120,
    }
]


invalid_events = [
    {
        "event_id": "evt_bad_001",
        "timestamp": "2026-04-29T14:00:00Z",
        "symbol": "BTC-USD",
        "side": "hold",
        "price": -1,
        "quantity": 0,
        "spread_bps": -5,
        "latency_ms": -10,
    }
]


print("\nDATA QUALITY TEST — VALID EVENTS")
print("=" * 80)
print(validate_events(valid_events))

print("\nDATA QUALITY TEST — INVALID EVENTS")
print("=" * 80)
print(validate_events(invalid_events))