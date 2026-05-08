import json
from pathlib import Path

import pandas as pd
import yfinance as yf

from flowpay_quant_engine import compute_quant_decision


START_DATE = "2025-01-01"
END_DATE = "2025-03-01"

TRAIN_END_DATE = "2025-02-01"

OUTPUT_DIR = Path("outputs/backtests")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_data() -> pd.DataFrame:
    df = yf.download("BTC-USD", start=START_DATE, end=END_DATE, interval="1d")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.dropna()

    if df.empty:
        raise ValueError("No BTC data fetched from Yahoo Finance")

    return df


def build_events(current_row, previous_row):
    current_price = float(current_row["Close"])
    previous_price = float(previous_row["Close"])
    volume = float(current_row["Volume"]) / 1_000_000

    side = "sell" if current_price < previous_price else "buy"
    spread = max(current_price * 0.001, 1)

    return [
        {
            "event_id": "bt_oos_001",
            "timestamp": str(current_row.name),
            "symbol": "BTC-USD",
            "side": side,
            "price": current_price,
            "volume": max(volume, 0.1),
            "bid": current_price - spread,
            "ask": current_price + spread,
            "bid_depth": 500000 if side == "buy" else 250000,
            "ask_depth": 500000 if side == "sell" else 250000,
        }
    ]


def exposure_from_severity(severity: str) -> float:
    if severity == "Critical":
        return 0.25
    if severity == "Defensive":
        return 0.40
    if severity == "Guarded":
        return 0.70
    return 1.00


def run_backtest(df: pd.DataFrame, label: str) -> pd.DataFrame:
    market_value = 10_000.0
    flowpay_value = 10_000.0
    history = []

    for i in range(1, len(df)):
        previous_row = df.iloc[i - 1]
        current_row = df.iloc[i]

        previous_price = float(previous_row["Close"])
        current_price = float(current_row["Close"])
        daily_return = current_price / previous_price - 1

        events = build_events(current_row, previous_row)
        decision = compute_quant_decision(events)

        mrs = decision.get("mrs")
        severity = decision.get("severity")
        action_bundle = decision.get("action_bundle")

        exposure = exposure_from_severity(severity)

        market_value *= 1 + daily_return
        flowpay_value *= 1 + daily_return * exposure

        history.append(
            {
                "period": label,
                "date": str(current_row.name),
                "price": current_price,
                "daily_return": daily_return,
                "mrs": mrs,
                "severity": severity,
                "action_bundle": action_bundle,
                "exposure": exposure,
                "market_value": market_value,
                "flowpay_value": flowpay_value,
            }
        )

    return pd.DataFrame(history)


def max_drawdown(series: pd.Series) -> float:
    return float(((series / series.cummax()) - 1).min() * 100)


def annualized_volatility(returns: pd.Series) -> float:
    return float(returns.std() * (365 ** 0.5) * 100)


def sharpe_ratio(returns: pd.Series) -> float:
    if returns.std() == 0:
        return 0.0
    return float((returns.mean() / returns.std()) * (365 ** 0.5))


def summarize(result: pd.DataFrame, label: str) -> dict:
    market_returns = result["market_value"].pct_change().dropna()
    flowpay_returns = result["flowpay_value"].pct_change().dropna()

    market_return = (result["market_value"].iloc[-1] / result["market_value"].iloc[0] - 1) * 100
    flowpay_return = (result["flowpay_value"].iloc[-1] / result["flowpay_value"].iloc[0] - 1) * 100

    return {
        "period": label,
        "market_return_pct": round(float(market_return), 2),
        "flowpay_return_pct": round(float(flowpay_return), 2),
        "return_improvement_points": round(float(flowpay_return - market_return), 2),
        "market_max_drawdown_pct": round(max_drawdown(result["market_value"]), 2),
        "flowpay_max_drawdown_pct": round(max_drawdown(result["flowpay_value"]), 2),
        "market_volatility_pct": round(annualized_volatility(market_returns), 2),
        "flowpay_volatility_pct": round(annualized_volatility(flowpay_returns), 2),
        "market_sharpe": round(sharpe_ratio(market_returns), 2),
        "flowpay_sharpe": round(sharpe_ratio(flowpay_returns), 2),
    }


def main():
    print("\nFLOWPAY BTC OUT-OF-SAMPLE BACKTEST")
    print("=" * 80)

    df = fetch_data()

    train_df = df[df.index < TRAIN_END_DATE]
    test_df = df[df.index >= TRAIN_END_DATE]

    train_result = run_backtest(train_df, "train")
    test_result = run_backtest(test_df, "out_of_sample_test")

    train_summary = summarize(train_result, "train")
    test_summary = summarize(test_result, "out_of_sample_test")

    full_results = pd.concat([train_result, test_result], ignore_index=True)

    output = {
        "asset": "BTC-USD",
        "start_date": START_DATE,
        "end_date": END_DATE,
        "train_end_date": TRAIN_END_DATE,
        "summaries": {
            "train": train_summary,
            "out_of_sample_test": test_summary,
        },
    }

    full_results.to_csv(OUTPUT_DIR / "flowpay_btc_oos_backtest_results.csv", index=False)

    with open(OUTPUT_DIR / "flowpay_btc_oos_backtest_summary.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print("\nTRAIN RESULTS")
    print("=" * 80)
    for key, value in train_summary.items():
        print(f"{key}: {value}")

    print("\nOUT-OF-SAMPLE TEST RESULTS")
    print("=" * 80)
    for key, value in test_summary.items():
        print(f"{key}: {value}")

    print("\nSaved:")
    print(OUTPUT_DIR / "flowpay_btc_oos_backtest_results.csv")
    print(OUTPUT_DIR / "flowpay_btc_oos_backtest_summary.json")


if __name__ == "__main__":
    main()