import pandas as pd
import yfinance as yf

from flowpay_quant_engine import compute_quant_decision


START_DATE = "2025-01-01"
END_DATE = "2025-03-01"


def fetch_data():
    df = yf.download("BTC-USD", start=START_DATE, end=END_DATE, interval="1d")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.dropna()

    if df.empty:
        raise ValueError("No data fetched from Yahoo Finance")

    return df


def build_events(current_row, previous_row):
    current_price = float(current_row["Close"])
    previous_price = float(previous_row["Close"])
    volume = float(current_row["Volume"]) / 1_000_000

    side = "sell" if current_price < previous_price else "buy"

    spread = max(current_price * 0.001, 1)

    return [
        {
            "event_id": "bt_001",
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


def simulate_strategy(df):
    initial_capital = 10000
    market_value = initial_capital
    flowpay_value = initial_capital

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

        if severity == "Critical":
            exposure = 0.25
        elif severity == "Defensive":
            exposure = 0.40
        elif severity == "Guarded":
            exposure = 0.70
        else:
            exposure = 1.00

        market_value = market_value * (1 + daily_return)
        flowpay_value = flowpay_value * (1 + daily_return * exposure)

        history.append(
            {
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


def main():
    print("\nFLOWPAY BTC BACKTEST")
    print("=" * 80)

    df = fetch_data()
    result = simulate_strategy(df)

    market_return = (result["market_value"].iloc[-1] / result["market_value"].iloc[0] - 1) * 100
    flowpay_return = (result["flowpay_value"].iloc[-1] / result["flowpay_value"].iloc[0] - 1) * 100

    max_market_drawdown = (
        (result["market_value"] / result["market_value"].cummax()) - 1
    ).min() * 100

    max_flowpay_drawdown = (
        (result["flowpay_value"] / result["flowpay_value"].cummax()) - 1
    ).min() * 100

    print("\nRESULTS")
    print("=" * 80)
    print(f"Market Return: {market_return:.2f}%")
    print(f"FlowPay Strategy Return: {flowpay_return:.2f}%")
    print(f"Market Max Drawdown: {max_market_drawdown:.2f}%")
    print(f"FlowPay Max Drawdown: {max_flowpay_drawdown:.2f}%")

    result.to_csv("flowpay_backtest_results.csv", index=False)
    print("\nSaved: flowpay_backtest_results.csv")


if __name__ == "__main__":
    main()