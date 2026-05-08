import json
import math
from datetime import datetime, timezone
from typing import Any


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

VALID_SIDES = {"buy", "sell"}


class QuantValidationError(ValueError):
    pass


def clamp(value: float, min_value: float = 0.0, max_value: float = 100.0) -> float:
    return max(min_value, min(max_value, value))


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def parse_timestamp(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception as exc:
        raise QuantValidationError(f"Invalid timestamp: {ts}") from exc


def to_positive_float(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except Exception as exc:
        raise QuantValidationError(f"Invalid numeric value for {field_name}: {value}") from exc

    if not math.isfinite(number):
        raise QuantValidationError(f"Non-finite numeric value for {field_name}: {value}")

    if number < 0:
        raise QuantValidationError(f"Negative value not allowed for {field_name}: {value}")

    return number


def validate_and_normalize_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not events:
        raise QuantValidationError("No events provided.")

    normalized = []

    for index, event in enumerate(events):
        missing = REQUIRED_FIELDS - set(event.keys())
        if missing:
            raise QuantValidationError(f"Event {index} missing fields: {sorted(missing)}")

        side = str(event["side"]).lower().strip()
        if side not in VALID_SIDES:
            raise QuantValidationError(f"Event {index} has invalid side: {event['side']}")

        timestamp = parse_timestamp(str(event["timestamp"]))

        price = to_positive_float(event["price"], "price")
        volume = to_positive_float(event["volume"], "volume")
        bid = to_positive_float(event["bid"], "bid")
        ask = to_positive_float(event["ask"], "ask")
        bid_depth = to_positive_float(event["bid_depth"], "bid_depth")
        ask_depth = to_positive_float(event["ask_depth"], "ask_depth")

        if price == 0:
            raise QuantValidationError(f"Event {index} price cannot be zero.")

        if volume == 0:
            raise QuantValidationError(f"Event {index} volume cannot be zero.")

        if bid == 0 or ask == 0:
            raise QuantValidationError(f"Event {index} bid/ask cannot be zero.")

        if ask < bid:
            raise QuantValidationError(
                f"Event {index} invalid market quote: ask is below bid."
            )

        normalized.append(
            {
                "timestamp": timestamp,
                "symbol": str(event["symbol"]).upper().strip(),
                "side": side,
                "price": price,
                "volume": volume,
                "bid": bid,
                "ask": ask,
                "bid_depth": bid_depth,
                "ask_depth": ask_depth,
            }
        )

    symbols = {event["symbol"] for event in normalized}
    if len(symbols) != 1:
        raise QuantValidationError(f"Mixed symbols detected: {sorted(symbols)}")

    normalized.sort(key=lambda event: event["timestamp"])

    return normalized


def compute_order_flow_imbalance(events: list[dict[str, Any]]) -> dict[str, float]:
    buy_volume = sum(event["volume"] for event in events if event["side"] == "buy")
    sell_volume = sum(event["volume"] for event in events if event["side"] == "sell")
    total_volume = buy_volume + sell_volume

    imbalance = safe_divide(sell_volume - buy_volume, total_volume)
    sell_pressure = max(0.0, imbalance)

    score = clamp(sell_pressure * 100)

    return {
        "buy_volume": round(buy_volume, 4),
        "sell_volume": round(sell_volume, 4),
        "total_volume": round(total_volume, 4),
        "order_flow_imbalance": round(imbalance, 4),
        "ofi_score": round(score, 2),
    }


def compute_liquidity_stress(events: list[dict[str, Any]]) -> dict[str, float]:
    first = events[0]
    last = events[-1]

    total_depth_start = first["bid_depth"] + first["ask_depth"]
    total_depth_end = last["bid_depth"] + last["ask_depth"]

    total_depth_drop_pct = safe_divide(
        total_depth_start - total_depth_end,
        total_depth_start,
    )

    bid_depth_drop_pct = safe_divide(
        first["bid_depth"] - last["bid_depth"],
        first["bid_depth"],
    )

    min_total_depth = min(event["bid_depth"] + event["ask_depth"] for event in events)
    min_depth_drop_pct = safe_divide(
        total_depth_start - min_total_depth,
        total_depth_start,
    )

    depth_imbalance_values = [
        abs(event["ask_depth"] - event["bid_depth"])
        / max(event["ask_depth"] + event["bid_depth"], 1)
        for event in events
    ]

    max_depth_imbalance = max(depth_imbalance_values)

    stress_factor = (
        0.35 * max(0.0, total_depth_drop_pct)
        + 0.35 * max(0.0, bid_depth_drop_pct)
        + 0.20 * max(0.0, min_depth_drop_pct)
        + 0.10 * max_depth_imbalance
    )

    score = clamp(stress_factor * 250)

    return {
        "total_depth_start": round(total_depth_start, 2),
        "total_depth_end": round(total_depth_end, 2),
        "total_depth_drop_pct": round(total_depth_drop_pct, 4),
        "bid_depth_drop_pct": round(bid_depth_drop_pct, 4),
        "min_total_depth": round(min_total_depth, 2),
        "min_depth_drop_pct": round(min_depth_drop_pct, 4),
        "max_depth_imbalance": round(max_depth_imbalance, 4),
        "liquidity_score": round(score, 2),
    }


def compute_volatility_instability(events: list[dict[str, Any]]) -> dict[str, float]:
    prices = [event["price"] for event in events]

    price_start = prices[0]
    price_end = prices[-1]
    high_price = max(prices)
    low_price = min(prices)

    close_to_close_move_pct = safe_divide(abs(price_end - price_start), price_start)
    high_low_range_pct = safe_divide(high_price - low_price, price_start)

    returns = []
    for previous, current in zip(prices, prices[1:]):
        returns.append(safe_divide(current - previous, previous))

    realized_volatility = 0.0
    if returns:
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        realized_volatility = math.sqrt(variance)

    instability_factor = (
        0.35 * close_to_close_move_pct
        + 0.45 * high_low_range_pct
        + 0.20 * realized_volatility
    )

    score = clamp(instability_factor * 1400)

    return {
        "price_start": round(price_start, 2),
        "price_end": round(price_end, 2),
        "high_price": round(high_price, 2),
        "low_price": round(low_price, 2),
        "close_to_close_move_pct": round(close_to_close_move_pct, 4),
        "high_low_range_pct": round(high_low_range_pct, 4),
        "realized_volatility": round(realized_volatility, 6),
        "volatility_score": round(score, 2),
    }


def compute_execution_risk(events: list[dict[str, Any]]) -> dict[str, float]:
    spread_percentages = []

    for event in events:
        mid_price = safe_divide(event["bid"] + event["ask"], 2)
        spread_pct = safe_divide(event["ask"] - event["bid"], mid_price)
        spread_percentages.append(spread_pct)

    last = events[-1]
    last_mid_price = safe_divide(last["bid"] + last["ask"], 2)
    last_spread_pct = safe_divide(last["ask"] - last["bid"], last_mid_price)

    average_spread_pct = sum(spread_percentages) / len(spread_percentages)
    max_spread_pct = max(spread_percentages)

    execution_factor = (
        0.40 * last_spread_pct
        + 0.35 * average_spread_pct
        + 0.25 * max_spread_pct
    )

    score = clamp(execution_factor * 2500)

    return {
        "last_bid": round(last["bid"], 2),
        "last_ask": round(last["ask"], 2),
        "last_mid_price": round(last_mid_price, 2),
        "last_spread_pct": round(last_spread_pct, 6),
        "average_spread_pct": round(average_spread_pct, 6),
        "max_spread_pct": round(max_spread_pct, 6),
        "execution_score": round(score, 2),
    }


def compute_trend_risk(
    current_mrs: float,
    previous_mrs_values: list[float] | None,
) -> dict[str, float]:
    if not previous_mrs_values:
        return {
            "previous_mrs_average": 0.0,
            "mrs_delta": 0.0,
            "trend_score": 0.0,
        }

    valid_values = [
        float(value)
        for value in previous_mrs_values
        if math.isfinite(float(value))
    ]

    if not valid_values:
        return {
            "previous_mrs_average": 0.0,
            "mrs_delta": 0.0,
            "trend_score": 0.0,
        }

    previous_average = sum(valid_values) / len(valid_values)
    delta = current_mrs - previous_average

    trend_score = clamp(max(0.0, delta) * 3.0)

    return {
        "previous_mrs_average": round(previous_average, 2),
        "mrs_delta": round(delta, 2),
        "trend_score": round(trend_score, 2),
    }


def amplify_score(score: float) -> float:
    return clamp(score ** 1.2)


def compute_market_risk_score(scores: dict[str, float]) -> float:
    ofi = amplify_score(scores["ofi_score"])
    liquidity = amplify_score(scores["liquidity_score"])
    volatility = amplify_score(scores["volatility_score"])
    execution = amplify_score(scores["execution_score"])
    trend = amplify_score(scores["trend_score"])

    market_risk_score = (
        0.32 * ofi
        + 0.22 * liquidity
        + 0.28 * volatility
        + 0.13 * execution
        + 0.05 * trend
    )

    # Stress overrides: prevent extreme single-signal events from being diluted.
    if scores["volatility_score"] >= 70:
        market_risk_score = max(market_risk_score, 75)

    if scores["ofi_score"] >= 90 and scores["liquidity_score"] >= 35:
        market_risk_score = max(market_risk_score, 70)

    if scores["ofi_score"] >= 95 and scores["volatility_score"] >= 45:
        market_risk_score = max(market_risk_score, 75)

    if scores["liquidity_score"] >= 70:
        market_risk_score = max(market_risk_score, 65)

    if scores["execution_score"] >= 80:
        market_risk_score = max(market_risk_score, 65)

    return round(clamp(market_risk_score), 2)


def classify_severity(market_risk_score: float) -> str:
    if market_risk_score < 25:
        return "Normal"
    if market_risk_score < 50:
        return "Guarded"
    if market_risk_score < 75:
        return "Defensive"
    return "Critical"


def detect_dominant_problem(scores: dict[str, float]) -> str:
    score_map = {
        "order_flow_imbalance": scores["ofi_score"],
        "liquidity_stress": scores["liquidity_score"],
        "volatility_instability": scores["volatility_score"],
        "execution_risk": scores["execution_score"],
        "trend_deterioration": scores["trend_score"],
    }

    sorted_scores = sorted(score_map.items(), key=lambda item: item[1], reverse=True)

    top_name, top_score = sorted_scores[0]
    second_name, second_score = sorted_scores[1]

    if top_score - second_score <= 10:
        return f"{top_name} + {second_name}"

    return top_name


def recommend_action(severity: str, dominant_problem: str) -> str:
    if severity == "Normal":
        return "monitor_only"

    if severity == "Guarded":
        return "increase_monitoring"

    if severity == "Defensive":
        if "liquidity_stress" in dominant_problem or "order_flow_imbalance" in dominant_problem:
            return "liquidity_rebalancing"
        if "volatility_instability" in dominant_problem:
            return "spread_widening"
        if "execution_risk" in dominant_problem:
            return "slippage_control"
        if "trend_deterioration" in dominant_problem:
            return "risk_limit_review"
        return "defensive_bundle"

    if severity == "Critical":
        if "liquidity_stress" in dominant_problem or "order_flow_imbalance" in dominant_problem:
            return "liquidity_rebalancing"
        if "volatility_instability" in dominant_problem:
            return "spread_widening"
        if "execution_risk" in dominant_problem:
            return "slippage_control"
        if "trend_deterioration" in dominant_problem:
            return "risk_limit_review"
        return "defensive_bundle"

    return "monitor_only"


def build_governance_status(severity: str, action: str) -> dict[str, Any]:
    if severity in {"Normal", "Guarded"}:
        return {
            "approved": True,
            "requires_human_review": False,
            "reason": "Recommendation-only action is proportionate to current severity.",
        }

    if severity == "Defensive":
        return {
            "approved": True,
            "requires_human_review": True,
            "reason": "Defensive market state requires operator review before real execution.",
        }

    return {
        "approved": False,
        "requires_human_review": True,
        "reason": "Critical market state blocks automatic approval. Human review required.",
    }


def build_decision_rationale(
    severity: str,
    dominant_problem: str,
    recommended_action: str,
) -> str:
    return (
        f"The market state is classified as {severity}. "
        f"The dominant problem is {dominant_problem}. "
        f"The recommended action is {recommended_action}. "
        f"This decision is recommendation-only and should not execute trades automatically."
    )


def compute_quant_decision(
    events: list[dict[str, Any]],
    previous_mrs_values: list[float] | None = None,
) -> dict[str, Any]:
    normalized_events = validate_and_normalize_events(events)

    symbol = normalized_events[0]["symbol"]
    window_start = normalized_events[0]["timestamp"]
    window_end = normalized_events[-1]["timestamp"]
    window_seconds = max(0.0, (window_end - window_start).total_seconds())

    ofi_result = compute_order_flow_imbalance(normalized_events)
    liquidity_result = compute_liquidity_stress(normalized_events)
    volatility_result = compute_volatility_instability(normalized_events)
    execution_result = compute_execution_risk(normalized_events)

    preliminary_scores = {
        "ofi_score": ofi_result["ofi_score"],
        "liquidity_score": liquidity_result["liquidity_score"],
        "volatility_score": volatility_result["volatility_score"],
        "execution_score": execution_result["execution_score"],
    }

    preliminary_mrs = compute_market_risk_score(
        {
            **preliminary_scores,
            "trend_score": 0.0,
        }
    )

    trend_result = compute_trend_risk(preliminary_mrs, previous_mrs_values)

    scores = {
        **preliminary_scores,
        "trend_score": trend_result["trend_score"],
    }

    market_risk_score = compute_market_risk_score(scores)
    severity = classify_severity(market_risk_score)
    dominant_problem = detect_dominant_problem(scores)
    recommended_action = recommend_action(severity, dominant_problem)

    

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "window": {
            "start_utc": window_start.isoformat(),
            "end_utc": window_end.isoformat(),
            "window_seconds": window_seconds,
            "event_count": len(normalized_events),
        },
        "raw_metrics": {
            "order_flow": ofi_result,
            "liquidity": liquidity_result,
            "volatility": volatility_result,
            "execution": execution_result,
            "trend": trend_result,
        },
        "metrics": {
            **scores,
            "market_risk_score": market_risk_score,
        },
        "market_risk_score": market_risk_score,
        "severity": severity,
        "dominant_problem": dominant_problem,
        "recommended_action": recommended_action,
        "decision_rationale": build_decision_rationale(
            severity=severity,
            dominant_problem=dominant_problem,
            recommended_action=recommended_action,
        ),
        "action_mode": "recommendation_only",
        "governance_status": build_governance_status(
            severity=severity,
            action=recommended_action,
        ),
        "model_limitations": [
            "Scores are heuristic and require empirical calibration.",
            "Stress overrides are designed for risk-control validation, not automated trading.",
            "This engine produces recommendations only, not automated execution.",
        ],
    }


def generate_demo_events() -> list[dict[str, Any]]:
    return [
        {
            "timestamp": "2026-04-24T10:00:01Z",
            "symbol": "BTC-USD",
            "side": "sell",
            "price": 67250,
            "volume": 2.4,
            "bid": 67240,
            "ask": 67270,
            "bid_depth": 950000,
            "ask_depth": 980000,
        },
        {
            "timestamp": "2026-04-24T10:00:08Z",
            "symbol": "BTC-USD",
            "side": "sell",
            "price": 67190,
            "volume": 3.1,
            "bid": 67180,
            "ask": 67220,
            "bid_depth": 820000,
            "ask_depth": 960000,
        },
        {
            "timestamp": "2026-04-24T10:00:15Z",
            "symbol": "BTC-USD",
            "side": "buy",
            "price": 67210,
            "volume": 1.1,
            "bid": 67195,
            "ask": 67235,
            "bid_depth": 790000,
            "ask_depth": 940000,
        },
        {
            "timestamp": "2026-04-24T10:00:23Z",
            "symbol": "BTC-USD",
            "side": "sell",
            "price": 67120,
            "volume": 2.8,
            "bid": 67100,
            "ask": 67160,
            "bid_depth": 660000,
            "ask_depth": 930000,
        },
        {
            "timestamp": "2026-04-24T10:00:30Z",
            "symbol": "BTC-USD",
            "side": "sell",
            "price": 67090,
            "volume": 2.2,
            "bid": 67080,
            "ask": 67140,
            "bid_depth": 620000,
            "ask_depth": 920000,
        },
    ]


def main() -> None:
    events = generate_demo_events()

    decision = compute_quant_decision(
        events=events,
        previous_mrs_values=[22.5, 28.1, 31.4],
    )

    print("\n=== FLOWPAY QUANT ENGINE V2 CALIBRATED ===\n")
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()