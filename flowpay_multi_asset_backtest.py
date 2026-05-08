import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

from flowpay_quant_engine import compute_quant_decision


ASSETS = {
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "QQQ": "Nasdaq QQQ ETF",
}

START_DATE = "2023-01-01"
END_DATE = "2025-03-01"

INITIAL_CAPITAL = 10_000.0

OUTPUT_DIR = Path("outputs/backtests")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SEVERITIES = {"Normal", "Guarded", "Defensive", "Critical"}

MRS_RANGES_BY_SEVERITY = {
    "Normal": (0, 24.99),
    "Guarded": (25, 49.99),
    "Defensive": (50, 74.99),
    "Critical": (75, float("inf")),
}

EXPOSURE_BY_SEVERITY = {
    "Normal": 1.00,
    "Guarded": 0.70,
    "Defensive": 0.40,
    "Critical": 0.25,
}

TRANSACTION_COST_BPS = {
    "BTC-USD": 12,
    "ETH-USD": 15,
    "QQQ": 2,
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

    df = df.dropna()

    required_columns = {"Open", "High", "Low", "Close", "Volume"}
    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(f"{symbol} missing columns: {sorted(missing)}")

    if df.empty:
        raise ValueError(f"No data fetched for {symbol}")

    return df


def calculate_return(current_price: float, previous_price: float) -> float:
    if previous_price <= 0:
        raise ValueError("Previous price must be positive")

    return current_price / previous_price - 1


def infer_signal_from_previous_bar(previous_row: pd.Series, prior_row: pd.Series) -> str:
    previous_close = float(previous_row["Close"])
    prior_close = float(prior_row["Close"])

    previous_return = calculate_return(previous_close, prior_close)

    if previous_return < 0:
        return "sell"

    return "buy"


def estimate_spread(current_price: float, symbol: str) -> float:
    if symbol == "QQQ":
        spread_bps = 2
    elif symbol == "BTC-USD":
        spread_bps = 10
    elif symbol == "ETH-USD":
        spread_bps = 12
    else:
        spread_bps = 10

    return max(current_price * spread_bps / 10_000, 0.01)


def build_events(symbol: str, current_row: pd.Series, previous_row: pd.Series, prior_row: pd.Series) -> List[Dict[str, Any]]:
    current_price = float(current_row["Close"])
    previous_price = float(previous_row["Close"])

    previous_volume = float(previous_row["Volume"])
    normalized_volume = max(previous_volume / 1_000_000, 0.1)

    signal_side = infer_signal_from_previous_bar(previous_row, prior_row)
    previous_return = calculate_return(previous_price, float(prior_row["Close"]))

    spread = estimate_spread(current_price, symbol)

    stress_multiplier = min(abs(previous_return) * 100, 5)

    bid_depth = max(50_000, 500_000 * (1 - min(stress_multiplier / 10, 0.8)))
    ask_depth = max(50_000, 500_000 * (1 + min(stress_multiplier / 10, 1.0)))

    if signal_side == "buy":
        bid_depth, ask_depth = ask_depth, bid_depth

    return [
        {
            "event_id": f"{symbol}_{str(current_row.name.date())}",
            "timestamp": current_row.name.isoformat(),
            "symbol": symbol,
            "side": signal_side,
            "price": current_price,
            "volume": normalized_volume,
            "bid": current_price - spread,
            "ask": current_price + spread,
            "bid_depth": round(bid_depth, 2),
            "ask_depth": round(ask_depth, 2),
        }
    ]


def validate_decision(decision: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors = []

    severity = decision.get("severity")
    mrs = decision.get("market_risk_score")
    action_bundle = decision.get("recommended_action")

    if severity not in SEVERITIES:
        errors.append(f"Invalid severity: {severity}")

    if mrs is None:
        errors.append("Missing MRS")
    else:
        try:
            mrs_float = float(mrs)
            if mrs_float < 0:
                errors.append(f"MRS must be non-negative: {mrs_float}")
        except (TypeError, ValueError):
            errors.append(f"MRS is not numeric: {mrs}")

    if not action_bundle:
        errors.append("Missing action_bundle")

    if severity in MRS_RANGES_BY_SEVERITY and mrs is not None:
        low, high = MRS_RANGES_BY_SEVERITY[severity]
        try:
            mrs_float = float(mrs)
            if not (low <= mrs_float <= high):
                errors.append(
                    f"MRS {mrs_float} is not aligned with severity {severity}. Expected range: {low} to {high}"
                )
        except (TypeError, ValueError):
            pass

    return len(errors) == 0, errors


def exposure_from_severity(severity: Optional[str]) -> float:
    return EXPOSURE_BY_SEVERITY.get(severity, 0.0)


def transaction_cost_rate(symbol: str, previous_exposure: float, new_exposure: float) -> float:
    turnover = abs(new_exposure - previous_exposure)
    cost_bps = TRANSACTION_COST_BPS.get(symbol, 10)
    return turnover * cost_bps / 10_000


def run_backtest(symbol: str, df: pd.DataFrame) -> pd.DataFrame:
    market_value = INITIAL_CAPITAL
    flowpay_value = INITIAL_CAPITAL

    previous_exposure = 1.0
    history = []

    for i in range(2, len(df)):
        prior_row = df.iloc[i - 2]
        previous_row = df.iloc[i - 1]
        current_row = df.iloc[i]

        previous_price = float(previous_row["Close"])
        current_price = float(current_row["Close"])

        daily_return = calculate_return(current_price, previous_price)

        events = build_events(symbol, current_row, previous_row, prior_row)
        decision = compute_quant_decision(events)

        decision_valid, decision_errors = validate_decision(decision)

        severity = decision.get("severity") if decision_valid else "Critical"
        mrs = decision.get("mrs")
        action_bundle = decision.get("recommended_action")

        exposure = exposure_from_severity(severity)

        cost_rate = transaction_cost_rate(symbol, previous_exposure, exposure)

        market_value *= 1 + daily_return
        flowpay_value *= 1 + (daily_return * exposure) - cost_rate

        previous_exposure = exposure

        history.append(
            {
                "asset": symbol,
                "date": current_row.name.isoformat(),
                "price": current_price,
                "daily_return": daily_return,
                "mrs": mrs,
                "severity": severity,
                "action_bundle": action_bundle,
                "decision_valid": decision_valid,
                "decision_errors": decision_errors,
                "exposure": exposure,
                "transaction_cost_rate": cost_rate,
                "market_value": market_value,
                "flowpay_value": flowpay_value,
            }
        )

    return pd.DataFrame(history)


def max_drawdown(series: pd.Series) -> float:
    drawdown = (series / series.cummax()) - 1
    return float(drawdown.min() * 100)


def recovery_days(series: pd.Series) -> Optional[int]:
    running_max = series.cummax()
    drawdown = series / running_max - 1

    underwater = drawdown < 0

    if not underwater.any():
        return 0

    max_recovery = 0
    current_recovery = 0

    for is_underwater in underwater:
        if is_underwater:
            current_recovery += 1
            max_recovery = max(max_recovery, current_recovery)
        else:
            current_recovery = 0

    return max_recovery


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


def downside_deviation(returns: pd.Series, periods_per_year: int) -> float:
    downside = returns[returns < 0]

    if downside.empty:
        return 0.0

    return float(downside.std() * math.sqrt(periods_per_year) * 100)


def summarize(result: pd.DataFrame, symbol: str) -> Dict[str, Any]:
    periods_per_year = TRADING_DAYS_BY_ASSET.get(symbol, 252)

    market_returns = result["market_value"].pct_change().dropna()
    flowpay_returns = result["flowpay_value"].pct_change().dropna()

    market_return = (result["market_value"].iloc[-1] / result["market_value"].iloc[0] - 1) * 100
    flowpay_return = (result["flowpay_value"].iloc[-1] / result["flowpay_value"].iloc[0] - 1) * 100

    valid_decision_rate = float(result["decision_valid"].mean()) if not result.empty else 0.0
    avg_exposure = float(result["exposure"].mean()) if not result.empty else 0.0
    avg_transaction_cost_bps = float(result["transaction_cost_rate"].mean() * 10_000) if not result.empty else 0.0

    return {
        "asset": symbol,
        "start_date": result["date"].iloc[0],
        "end_date": result["date"].iloc[-1],
        "data_frequency": "daily",
        "important_limitation": "This is a daily risk-control backtest, not a 30-second event-driven production latency validation.",
        "market_return_pct": round(float(market_return), 2),
        "flowpay_return_pct": round(float(flowpay_return), 2),
        "return_difference_points": round(float(flowpay_return - market_return), 2),
        "market_max_drawdown_pct": round(max_drawdown(result["market_value"]), 2),
        "flowpay_max_drawdown_pct": round(max_drawdown(result["flowpay_value"]), 2),
        "drawdown_reduction_points": round(
            abs(max_drawdown(result["market_value"])) - abs(max_drawdown(result["flowpay_value"])),
            2,
        ),
        "market_recovery_days": recovery_days(result["market_value"]),
        "flowpay_recovery_days": recovery_days(result["flowpay_value"]),
        "market_volatility_pct": round(annualized_volatility(market_returns, periods_per_year), 2),
        "flowpay_volatility_pct": round(annualized_volatility(flowpay_returns, periods_per_year), 2),
        "market_downside_deviation_pct": round(downside_deviation(market_returns, periods_per_year), 2),
        "flowpay_downside_deviation_pct": round(downside_deviation(flowpay_returns, periods_per_year), 2),
        "market_sharpe": round(sharpe_ratio(market_returns, periods_per_year), 2),
        "flowpay_sharpe": round(sharpe_ratio(flowpay_returns, periods_per_year), 2),
        "risk_free_rate_annual": RISK_FREE_RATE_ANNUAL,
        "avg_flowpay_exposure": round(avg_exposure, 4),
        "avg_transaction_cost_bps": round(avg_transaction_cost_bps, 4),
        "valid_decision_rate": round(valid_decision_rate, 4),
    }


def generate_readme(summary_output: Dict[str, Any]) -> None:
    lines = [
        "# FlowPay Multi-Asset Risk-Control Backtest",
        "",
        "## Important Limitation",
        "",
        "This backtest uses daily market data. It does **not** validate the production 30-second event-driven behavior of FlowPay.",
        "",
        "Its purpose is narrower: validate whether FlowPay-style severity signals can reduce exposure during adverse daily market regimes.",
        "",
        "## Methodology Fixes",
        "",
        "- No direct same-bar look-ahead signal construction.",
        "- Events are built from prior-bar information.",
        "- Transaction costs are included.",
        "- Sharpe ratio includes a risk-free rate.",
        "- Crypto and ETF annualization use different trading-day assumptions.",
        "- Model outputs are validated before being used.",
        "- Drawdown recovery days are reported.",
        "",
        "## Files Generated",
        "",
        "- `flowpay_multi_asset_backtest_results.csv`",
        "- `flowpay_multi_asset_backtest_summary.json`",
        "- `flowpay_multi_asset_backtest_readme.md`",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(summary_output, indent=2),
        "```",
    ]

    (OUTPUT_DIR / "flowpay_multi_asset_backtest_readme.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def main() -> None:
    print("\nFLOWPAY MULTI-ASSET RISK-CONTROL BACKTEST")
    print("=" * 80)
    print("Important: this is daily risk-control validation, not 30-second event-driven validation.")

    all_results = []
    summaries = []

    for symbol, name in ASSETS.items():
        print(f"\nRunning asset: {symbol} ({name})")
        print("-" * 80)

        df = fetch_data(symbol)
        result = run_backtest(symbol, df)

        if result.empty:
            print(f"No result generated for {symbol}")
            continue

        summary = summarize(result, symbol)

        all_results.append(result)
        summaries.append(summary)

        print(f"Market Return: {summary['market_return_pct']}%")
        print(f"FlowPay Return: {summary['flowpay_return_pct']}%")
        print(f"Difference: {summary['return_difference_points']} pts")
        print(f"Market Drawdown: {summary['market_max_drawdown_pct']}%")
        print(f"FlowPay Drawdown: {summary['flowpay_max_drawdown_pct']}%")
        print(f"Drawdown Reduction: {summary['drawdown_reduction_points']} pts")
        print(f"Market Sharpe: {summary['market_sharpe']}")
        print(f"FlowPay Sharpe: {summary['flowpay_sharpe']}")
        print(f"Valid Decision Rate: {summary['valid_decision_rate']:.0%}")

    if not all_results:
        raise RuntimeError("No backtest results were generated.")

    full_results = pd.concat(all_results, ignore_index=True)

    summary_output = {
        "start_date": START_DATE,
        "end_date": END_DATE,
        "assets": ASSETS,
        "initial_capital": INITIAL_CAPITAL,
        "risk_free_rate_annual": RISK_FREE_RATE_ANNUAL,
        "transaction_cost_bps": TRANSACTION_COST_BPS,
        "exposure_by_severity": EXPOSURE_BY_SEVERITY,
        "methodology_note": "Daily risk-control backtest. Not a high-frequency execution simulation.",
        "summaries": summaries,
    }

    full_results.to_csv(
        OUTPUT_DIR / "flowpay_multi_asset_backtest_results.csv",
        index=False,
    )

    with open(OUTPUT_DIR / "flowpay_multi_asset_backtest_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary_output, f, indent=2)

    generate_readme(summary_output)

    print("\nSaved:")
    print(OUTPUT_DIR / "flowpay_multi_asset_backtest_results.csv")
    print(OUTPUT_DIR / "flowpay_multi_asset_backtest_summary.json")
    print(OUTPUT_DIR / "flowpay_multi_asset_backtest_readme.md")


if __name__ == "__main__":
    main()