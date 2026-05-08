from __future__ import annotations

import math
import random
from typing import Any


SYMBOL = "BTC-USD"
RANDOM_SEED = 42

REQUIRED_FIELDS = {
    "timestamp",
    "symbol",
    "side",
    "price",
    "volume",
    "bid",
    "ask",
    "bid_depth",
    "ask_depth",
}


def validate_events(events: list[dict[str, Any]], scenario_name: str) -> None:
    if not events:
        raise ValueError(f"Scenario '{scenario_name}' has no events.")

    for index, event in enumerate(events):
        missing_fields = REQUIRED_FIELDS - set(event.keys())
        if missing_fields:
            raise ValueError(
                f"Scenario '{scenario_name}', event {index} missing fields: {sorted(missing_fields)}"
            )

        if event["symbol"] != SYMBOL:
            raise ValueError(
                f"Scenario '{scenario_name}', event {index} has invalid symbol: {event['symbol']}"
            )

        if str(event["side"]).lower() not in {"buy", "sell"}:
            raise ValueError(
                f"Scenario '{scenario_name}', event {index} has invalid side: {event['side']}"
            )

        for field in ["price", "volume", "bid", "ask", "bid_depth", "ask_depth"]:
            value = float(event[field])

            if not math.isfinite(value):
                raise ValueError(
                    f"Scenario '{scenario_name}', event {index} has non-finite {field}: {value}"
                )

            if value < 0:
                raise ValueError(
                    f"Scenario '{scenario_name}', event {index} has negative {field}: {value}"
                )

        if float(event["price"]) == 0:
            raise ValueError(
                f"Scenario '{scenario_name}', event {index} price cannot be zero."
            )

        if float(event["bid"]) == 0 or float(event["ask"]) == 0:
            raise ValueError(
                f"Scenario '{scenario_name}', event {index} bid/ask cannot be zero."
            )

        if float(event["ask"]) < float(event["bid"]):
            raise ValueError(
                f"Scenario '{scenario_name}', event {index} has ask below bid."
            )


def make_event(
    timestamp: str,
    side: str,
    price: float,
    volume: float,
    bid: float,
    ask: float,
    bid_depth: float,
    ask_depth: float,
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "symbol": SYMBOL,
        "side": side,
        "price": round(price, 2),
        "volume": round(volume, 4),
        "bid": round(bid, 2),
        "ask": round(ask, 2),
        "bid_depth": round(bid_depth, 2),
        "ask_depth": round(ask_depth, 2),
    }


def apply_market_noise(
    events: list[dict[str, Any]],
    price_noise: float = 3.0,
    volume_noise_pct: float = 0.08,
    depth_noise_pct: float = 0.03,
) -> list[dict[str, Any]]:
    noisy_events = []

    for event in events:
        price_shift = random.uniform(-price_noise, price_noise)
        volume_factor = random.uniform(1 - volume_noise_pct, 1 + volume_noise_pct)
        bid_depth_factor = random.uniform(1 - depth_noise_pct, 1 + depth_noise_pct)
        ask_depth_factor = random.uniform(1 - depth_noise_pct, 1 + depth_noise_pct)

        spread = float(event["ask"]) - float(event["bid"])
        new_price = float(event["price"]) + price_shift
        new_bid = new_price - spread / 2
        new_ask = new_price + spread / 2

        noisy_events.append(
            {
                **event,
                "price": round(new_price, 2),
                "volume": round(float(event["volume"]) * volume_factor, 4),
                "bid": round(new_bid, 2),
                "ask": round(new_ask, 2),
                "bid_depth": round(float(event["bid_depth"]) * bid_depth_factor, 2),
                "ask_depth": round(float(event["ask_depth"]) * ask_depth_factor, 2),
            }
        )

    return noisy_events


def sort_and_validate_scenarios(
    scenarios: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    cleaned: dict[str, list[dict[str, Any]]] = {}

    for scenario_name, events in scenarios.items():
        sorted_events = sorted(events, key=lambda event: event["timestamp"])
        validate_events(sorted_events, scenario_name)
        cleaned[scenario_name] = sorted_events

    return cleaned


def build_scenarios(add_noise: bool = True) -> dict[str, list[dict[str, Any]]]:
    random.seed(RANDOM_SEED)

    scenarios = {
        "normal_market": [
            make_event("2026-04-24T10:00:01Z", "buy", 67000, 1.0, 66995, 67005, 1000000, 1005000),
            make_event("2026-04-24T10:00:08Z", "sell", 67002, 1.1, 66997, 67007, 1002000, 1003000),
            make_event("2026-04-24T10:00:15Z", "buy", 67001, 0.9, 66996, 67006, 1001000, 1004000),
            make_event("2026-04-24T10:00:30Z", "sell", 67003, 1.0, 66998, 67008, 1000000, 1002000),
        ],
        "guarded_selling_pressure": [
            make_event("2026-04-24T10:01:01Z", "sell", 67000, 2.4, 66990, 67010, 980000, 1000000),
            make_event("2026-04-24T10:01:08Z", "sell", 66970, 2.8, 66960, 66985, 900000, 990000),
            make_event("2026-04-24T10:01:15Z", "buy", 66980, 0.8, 66970, 66995, 880000, 980000),
            make_event("2026-04-24T10:01:30Z", "sell", 66940, 2.5, 66925, 66955, 820000, 970000),
        ],
        "liquidity_stress": [
            make_event("2026-04-24T10:02:01Z", "buy", 67000, 1.0, 66990, 67010, 1200000, 1200000),
            make_event("2026-04-24T10:02:08Z", "sell", 66990, 1.2, 66975, 67005, 850000, 1050000),
            make_event("2026-04-24T10:02:15Z", "sell", 66970, 1.4, 66950, 66995, 620000, 950000),
            make_event("2026-04-24T10:02:30Z", "sell", 66950, 1.1, 66925, 66985, 500000, 900000),
        ],
        "execution_risk_spread_widening": [
            make_event("2026-04-24T10:03:01Z", "buy", 67000, 1.0, 66995, 67005, 1000000, 1000000),
            make_event("2026-04-24T10:03:08Z", "sell", 66990, 1.1, 66970, 67030, 980000, 990000),
            make_event("2026-04-24T10:03:15Z", "buy", 66995, 0.9, 66950, 67050, 960000, 980000),
            make_event("2026-04-24T10:03:30Z", "sell", 66980, 1.0, 66930, 67070, 940000, 970000),
        ],
        "defensive_combined_crisis": [
            make_event("2026-04-24T10:04:01Z", "sell", 67000, 3.0, 66990, 67015, 1100000, 1200000),
            make_event("2026-04-24T10:04:08Z", "sell", 66880, 3.5, 66860, 66910, 760000, 1100000),
            make_event("2026-04-24T10:04:15Z", "sell", 66790, 4.0, 66750, 66830, 520000, 980000),
            make_event("2026-04-24T10:04:30Z", "buy", 66820, 0.5, 66770, 66860, 430000, 930000),
        ],
        "critical_market_breakdown": [
            make_event("2026-04-24T10:05:01Z", "sell", 67000, 5.0, 66980, 67030, 1300000, 1200000),
            make_event("2026-04-24T10:05:08Z", "sell", 66400, 6.5, 66300, 66520, 650000, 1000000),
            make_event("2026-04-24T10:05:15Z", "sell", 65900, 8.0, 65750, 66150, 260000, 850000),
            make_event("2026-04-24T10:05:30Z", "sell", 65300, 9.0, 65000, 65600, 120000, 700000),
        ],
    }

    if add_noise:
        scenarios = {
            scenario_name: apply_market_noise(events)
            for scenario_name, events in scenarios.items()
        }

    return sort_and_validate_scenarios(scenarios)


def main() -> None:
    scenarios = build_scenarios(add_noise=True)

    print(f"Loaded {len(scenarios)} FlowPay scenarios:")

    for name, events in scenarios.items():
        print(f"- {name}: {len(events)} events")

    print("\nValidation completed successfully.")


if __name__ == "__main__":
    main()