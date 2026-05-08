import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

from flowpay_quant_engine import compute_quant_decision


ASSETS = {
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "QQQ": "Nasdaq QQQ ETF",
}

START_DATE = "2021-01-01"
END_DATE = "2025-03-01"

INITIAL_CAPITAL = 10_000.0
ROLLING_WINDOW_DAYS = 20

OUTPUT_DIR = Path("outputs/backtests")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EXPOSURE_BY_SEVERITY = {
    "Normal": 1.00,
    "Guarded": 0.70,
    "Defensive": 0.40,
    "Critical": 0.25,
}

SEVERITY_VALUES = set(EXPOSURE_BY_SEVERITY.keys())

TRANSACTION_COST_BPS = {
    "BTC-USD": 20,
    "ETH-USD": 25,
    "QQQ": 3,
}

TRADING_DAYS_BY_ASSET = {
    "BTC-USD": 365,
    "ETH-USD": 365,
    "QQQ": 252,
}

RISK_FREE_RATE_ANNUAL = 0.04


def fetch_data(symbol: str) -> pd.DataFrame:
    df = yf.download(
        symbol,
        start=START_DATE,
        end=END_DATE,
        interval="1d",
        auto_adjust=True,
        progress=False,
    )

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    required_columns = {"Open", "High", "Low", "Close", "Volume"}
    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise ValueError(f"{symbol} missing required columns: {sorted(missing_columns)}")

    df = df.dropna(subset=list(required_columns))

    if df.empty:
        raise ValueError(f"No usable data fetched for {symbol}")

    df["source_symbol"] = symbol
    return df


def calculate_return(current_price: float, previous_price: float) -> float:
    if previous_price <= 0:
        raise ValueError("Previous price must be positive")
    return current_price / previous_price - 1


def asset_stress_threshold(symbol: str) -> float:
    if symbol in {"BTC-USD", "ETH-USD"}:
        return -15.0
    return -8.0


def estimate_spread_bps(symbol: str, previous_abs_return: float) -> float:
    base_spread = {
        "BTC-USD": 12,
        "ETH-USD": 15,
        "QQQ": 2,
    }.get(symbol, 10)

    stress_addon = min(previous_abs_return * 10_000 * 0.10, 50)
    return base_spread + stress_addon


def infer_side_from_prior_information(previous_row: pd.Series, prior_row: pd.Series) -> str:
    previous_return = calculate_return(
        float(previous_row["Close"]),
        float(prior_row["Close"]),
    )

    return "sell" if previous_return < 0 else "buy"


def build_events_from_previous_bar(
    symbol: str,
    current_row: pd.Series,
    previous_row: pd.Series,
    prior_row: pd.Series,
) -> List[Dict[str, Any]]:
    previous_price = float(previous_row["Close"])
    previous_volume = float(previous_row["Volume"])
    prior_price = float(prior_row["Close"])

    previous_return = calculate_return(previous_price, prior_price)
    side = infer_side_from_prior_information(previous_row, prior_row)

    spread_bps = estimate_spread_bps(symbol, abs(previous_return))
    spread = max(previous_price * spread_bps / 10_000, 0.01)

    stress_multiplier = min(abs(previous_return) * 100, 10)

    bid_depth = max(50_000, 500_000 * (1 - min(stress_multiplier / 10, 0.85)))
    ask_depth = max(50_000, 500_000 * (1 + min(stress_multiplier / 10, 1.25)))

    if side == "buy":
        bid_depth, ask_depth = ask_depth, bid_depth

    return [
        {
            "event_id": f"{symbol}_{previous_row.name.date()}",
            "timestamp": previous_row.name.isoformat(),
            "symbol": symbol,
            "side": side,
            "price": previous_price,
            "volume": max(previous_volume / 1_000_000, 0.1),
            "bid": previous_price - spread,
            "ask": previous_price + spread,
            "bid_depth": round(bid_depth, 2),
            "ask_depth": round(ask_depth, 2),
        }
    ]


def normalize_decision(decision: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "mrs": decision.get("mrs", decision.get("market_risk_score")),
        "severity": decision.get("severity"),
        "action_bundle": decision.get("action_bundle", decision.get("recommended_action")),
    }


def validate_decision(decision: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors = []

    normalized = normalize_decision(decision)

    severity = normalized["severity"]
    mrs = normalized["mrs"]
    action_bundle = normalized["action_bundle"]

    if severity not in SEVERITY_VALUES:
        errors.append(f"Invalid severity: {severity}")

    try:
        mrs_float = float(mrs)
        if math.isnan(mrs_float) or mrs_float < 0:
            errors.append(f"Invalid MRS value: {mrs}")
    except (TypeError, ValueError):
        errors.append(f"MRS is missing or non-numeric: {mrs}")

    if not action_bundle:
        errors.append("Missing action_bundle / recommended_action")

    return len(errors) == 0, errors


def exposure_from_severity(severity: Optional[str]) -> float:
    if severity not in EXPOSURE_BY_SEVERITY:
        return 0.0
    return EXPOSURE_BY_SEVERITY[severity]


def transaction_cost_rate(symbol: str, previous_exposure: float, new_exposure: float) -> float:
    turnover = abs(new_exposure - previous_exposure)
    cost_bps = TRANSACTION_COST_BPS.get(symbol, 10)
    return turnover * cost_bps / 10_000


def mark_stress_periods(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    df = df.copy()

    threshold = asset_stress_threshold(symbol)

    df["rolling_return_pct"] = (
        df["Close"] / df["Close"].shift(ROLLING_WINDOW_DAYS) - 1
    ) * 100

    df["stress_period"] = df["rolling_return_pct"] <= threshold
    df["stress_threshold_pct"] = threshold

    return df


def run_backtest(symbol: str, df: pd.DataFrame) -> pd.DataFrame:
    market_value = INITIAL_CAPITAL
    flowpay_value = INITIAL_CAPITAL
    sma_risk_value = INITIAL_CAPITAL

    previous_flowpay_exposure = 1.0
    previous_sma_exposure = 1.0

    history = []

    df = mark_stress_periods(df, symbol)
    df["sma_50"] = df["Close"].rolling(50).mean()

    for i in range(2, len(df)):
        prior_row = df.iloc[i - 2]
        previous_row = df.iloc[i - 1]
        current_row = df.iloc[i]

        previous_price = float(previous_row["Close"])
        current_price = float(current_row["Close"])

        daily_return = calculate_return(current_price, previous_price)

        events = build_events_from_previous_bar(
            symbol=symbol,
            current_row=current_row,
            previous_row=previous_row,
            prior_row=prior_row,
        )

        raw_decision = compute_quant_decision(events)
        decision_valid, decision_errors = validate_decision(raw_decision)
        decision = normalize_decision(raw_decision)

        severity = decision["severity"] if decision_valid else "Critical"
        mrs = decision["mrs"]
        action_bundle = decision["action_bundle"]

        flowpay_exposure = exposure_from_severity(severity)

        if pd.notna(previous_row.get("sma_50")) and previous_price >= float(previous_row["sma_50"]):
            sma_exposure = 1.0
        else:
            sma_exposure = 0.5

        flowpay_cost = transaction_cost_rate(symbol, previous_flowpay_exposure, flowpay_exposure)
        sma_cost = transaction_cost_rate(symbol, previous_sma_exposure, sma_exposure)

        market_value *= 1 + daily_return
        flowpay_value *= 1 + (daily_return * flowpay_exposure) - flowpay_cost
        sma_risk_value *= 1 + (daily_return * sma_exposure) - sma_cost

        previous_flowpay_exposure = flowpay_exposure
        previous_sma_exposure = sma_exposure

        history.append(
            {
                "asset": symbol,
                "date": current_row.name.isoformat(),
                "price": current_price,
                "daily_return": daily_return,
                "rolling_return_pct": current_row.get("rolling_return_pct"),
                "stress_threshold_pct": current_row.get("stress_threshold_pct"),
                "stress_period": bool(current_row.get("stress_period")),
                "mrs": mrs,
                "severity": severity,
                "action_bundle": action_bundle,
                "decision_valid": decision_valid,
                "decision_errors": decision_errors,
                "flowpay_exposure": flowpay_exposure,
                "sma_exposure": sma_exposure,
                "flowpay_transaction_cost_rate": flowpay_cost,
                "sma_transaction_cost_rate": sma_cost,
                "market_value": market_value,
                "flowpay_value": flowpay_value,
                "sma_risk_value": sma_risk_value,
            }
        )

    return pd.DataFrame(history)


def max_drawdown(series: pd.Series) -> float:
    return float(((series / series.cummax()) - 1).min() * 100)


def recovery_days(series: pd.Series) -> int:
    drawdown = series / series.cummax() - 1
    max_days = 0
    current_days = 0

    for value in drawdown:
        if value < 0:
            current_days += 1
            max_days = max(max_days, current_days)
        else:
            current_days = 0

    return max_days


def annualized_volatility(returns: pd.Series, periods_per_year: int) -> float:
    if returns.empty:
        return 0.0
    return float(returns.std() * math.sqrt(periods_per_year) * 100)


def sharpe_ratio(returns: pd.Series, periods_per_year: int) -> float:
    if returns.empty or returns.std() == 0:
        return 0.0

    period_risk_free = RISK_FREE_RATE_ANNUAL / periods_per_year
    excess_returns = returns - period_risk_free

    return float((excess_returns.mean() / returns.std()) * math.sqrt(periods_per_year))


def sortino_ratio(returns: pd.Series, periods_per_year: int) -> float:
    if returns.empty:
        return 0.0

    period_risk_free = RISK_FREE_RATE_ANNUAL / periods_per_year
    excess_returns = returns - period_risk_free
    downside = excess_returns[excess_returns < 0]

    if downside.empty or downside.std() == 0:
        return 0.0

    return float((excess_returns.mean() / downside.std()) * math.sqrt(periods_per_year))


def summarize_strategy(
    result: pd.DataFrame,
    symbol: str,
    value_column: str,
    label: str,
) -> Dict[str, Any]:
    periods_per_year = TRADING_DAYS_BY_ASSET.get(symbol, 252)
    returns = result[value_column].pct_change().dropna()

    total_return = (result[value_column].iloc[-1] / result[value_column].iloc[0] - 1) * 100

    return {
        "strategy": label,
        "total_return_pct": round(float(total_return), 2),
        "max_drawdown_pct": round(max_drawdown(result[value_column]), 2),
        "recovery_days": recovery_days(result[value_column]),
        "volatility_pct": round(annualized_volatility(returns, periods_per_year), 2),
        "sharpe": round(sharpe_ratio(returns, periods_per_year), 2),
        "sortino": round(sortino_ratio(returns, periods_per_year), 2),
    }


def summarize(result: pd.DataFrame, symbol: str) -> Dict[str, Any]:
    stress = result[result["stress_period"] == True].copy()

    mrs_numeric = pd.to_numeric(result["mrs"], errors="coerce")
    valid_mrs_rate = float(mrs_numeric.notna().mean()) if not result.empty else 0.0

    full_period = {
        "market_buy_hold": summarize_strategy(result, symbol, "market_value", "market_buy_hold"),
        "flowpay_risk_control": summarize_strategy(result, symbol, "flowpay_value", "flowpay_risk_control"),
        "sma_risk_baseline": summarize_strategy(result, symbol, "sma_risk_value", "sma_risk_baseline"),
    }

    stress_summary = None

    if not stress.empty:
        stress_summary = {
            "stress_days": int(len(stress)),
            "avg_flowpay_exposure": round(float(stress["flowpay_exposure"].mean()), 4),
            "avg_sma_exposure": round(float(stress["sma_exposure"].mean()), 4),
            "avg_mrs": round(float(pd.to_numeric(stress["mrs"], errors="coerce").mean()), 2),
            "market_buy_hold": summarize_strategy(stress, symbol, "market_value", "market_buy_hold"),
            "flowpay_risk_control": summarize_strategy(stress, symbol, "flowpay_value", "flowpay_risk_control"),
            "sma_risk_baseline": summarize_strategy(stress, symbol, "sma_risk_value", "sma_risk_baseline"),
        }

    return {
        "asset": symbol,
        "data_frequency": "daily",
        "validation_type": "risk-control stress validation, not high-frequency execution backtest",
        "stress_threshold_pct": asset_stress_threshold(symbol),
        "rolling_window_days": ROLLING_WINDOW_DAYS,
        "valid_decision_rate": round(float(result["decision_valid"].mean()), 4),
        "valid_mrs_rate": round(valid_mrs_rate, 4),
        "full_period": full_period,
        "stress_period_only": stress_summary,
    }


def generate_readme(output: Dict[str, Any]) -> None:
    lines = [
        "# FlowPay Stress-Window Risk-Control Validation",
        "",
        "## What this validates",
        "",
        "This validates whether FlowPay-style risk severity signals reduce exposure during adverse daily market regimes.",
        "",
        "## What this does NOT validate",
        "",
        "- It does not validate 30-second event-driven latency.",
        "- It does not simulate real order execution.",
        "- It does not use live order book data.",
        "- It should not be presented as a true institutional trading backtest.",
        "",
        "## Methodology Improvements",
        "",
        "- Signals use prior-bar information.",
        "- Events are built from previous known market state.",
        "- Transaction costs are included.",
        "- Asset-specific stress thresholds are used.",
        "- A simple moving average risk baseline is included.",
        "- Full-period and stress-period results are both reported.",
        "- Model output fields are normalized and validated.",
        "- Sharpe and Sortino ratios are included.",
        "",
        "## Output",
        "",
        "```json",
        json.dumps(output, indent=2),
        "```",
    ]

    (OUTPUT_DIR / "flowpay_stress_window_backtest_readme.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def main() -> None:
    print("\nFLOWPAY STRESS-WINDOW RISK-CONTROL VALIDATION")
    print("=" * 80)
    print("Important: this is not a true 30-second event-driven market execution backtest.")

    all_results = []
    summaries = []

    for symbol, name in ASSETS.items():
        print(f"\nRunning asset: {symbol} ({name})")
        print("-" * 80)

        df = fetch_data(symbol)
        result = run_backtest(symbol, df)
        summary = summarize(result, symbol)

        all_results.append(result)
        summaries.append(summary)

        print(json.dumps(summary, indent=2))

    full_results = pd.concat(all_results, ignore_index=True)

    output = {
        "start_date": START_DATE,
        "end_date": END_DATE,
        "initial_capital": INITIAL_CAPITAL,
        "risk_free_rate_annual": RISK_FREE_RATE_ANNUAL,
        "transaction_cost_bps": TRANSACTION_COST_BPS,
        "exposure_by_severity": EXPOSURE_BY_SEVERITY,
        "methodology_note": "Daily risk-control validation only. Not high-frequency execution validation.",
        "summaries": summaries,
    }

    full_results.to_csv(
        OUTPUT_DIR / "flowpay_stress_window_backtest_results.csv",
        index=False,
    )

    with open(OUTPUT_DIR / "flowpay_stress_window_backtest_summary.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    generate_readme(output)

    print("\nSaved:")
    print(OUTPUT_DIR / "flowpay_stress_window_backtest_results.csv")
    print(OUTPUT_DIR / "flowpay_stress_window_backtest_summary.json")
    print(OUTPUT_DIR / "flowpay_stress_window_backtest_readme.md")


if __name__ == "__main__":
    main()