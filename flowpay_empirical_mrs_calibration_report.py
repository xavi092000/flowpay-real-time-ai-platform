import json
import math
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Dict, List, Tuple

import pandas as pd
import yfinance as yf

from flowpay_quant_engine import compute_quant_decision


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "calibration"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ASSETS = {
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "QQQ": "Nasdaq QQQ ETF",
}

START_DATE = "2021-01-01"
END_DATE = "2025-03-01"

VALID_SEVERITIES = {"Normal", "Guarded", "Defensive", "Critical"}

EXPECTED_ACTIONS = {
    "Normal": {"monitor_only", "monitoring_bundle"},
    "Guarded": {"increase_monitoring", "early_warning_bundle"},
    "Defensive": {
        "defensive_bundle",
        "liquidity_rebalancing",
        "spread_widening",
        "slippage_control",
        "risk_limit_review",
    },
    "Critical": {
        "defensive_bundle",
        "liquidity_rebalancing",
        "spread_widening",
        "slippage_control",
        "risk_limit_review",
        "survival_mode",
        "circuit_breaker_review",
    },
}


def fetch_market_data(symbol: str) -> pd.DataFrame:
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

    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"{symbol} missing columns: {sorted(missing)}")

    df = df.dropna(subset=list(required))

    if df.empty:
        raise ValueError(f"No usable data for {symbol}")

    return df


def calculate_return(current_price: float, previous_price: float) -> float:
    if previous_price <= 0:
        raise ValueError("Previous price must be positive")

    return current_price / previous_price - 1


def build_event_from_prior_bar(
    symbol: str,
    previous_row: pd.Series,
    prior_row: pd.Series,
) -> List[Dict[str, Any]]:
    previous_volume = float(previous_row["Volume"])

    open_price = float(previous_row["Open"])
    high_price = float(previous_row["High"])
    low_price = float(previous_row["Low"])
    close_price = float(previous_row["Close"])

    base_timestamp = previous_row.name
    volatility_proxy = abs(high_price / low_price - 1)

    if symbol == "QQQ":
        base_spread_bps = 3
        volume_divisor = 100_000
    else:
        base_spread_bps = 15
        volume_divisor = 100_000

    stress_spread_bps = min(volatility_proxy * 10_000 * 0.25, 200)
    spread_bps = base_spread_bps + stress_spread_bps

    liquidity_stress = min(volatility_proxy * 1000, 100)

    def make_event(price: float, side: str, ts_offset: int) -> Dict[str, Any]:
        spread = max(price * spread_bps / 10_000, 0.01)

        bid_depth = max(
            50_000,
            500_000 * (1 - min(liquidity_stress / 100, 0.90)),
        )
        ask_depth = max(
            50_000,
            500_000 * (1 + min(liquidity_stress / 100, 1.50)),
        )

        if side == "buy":
            bid_depth, ask_depth = ask_depth, bid_depth

        return {
            "event_id": f"{symbol}_{base_timestamp.date()}_{ts_offset}",
            "timestamp": (base_timestamp + pd.Timedelta(seconds=ts_offset)).isoformat(),
            "symbol": symbol,
            "side": side,
            "price": price,
            "volume": max(previous_volume / volume_divisor, 1.0),
            "bid": price - spread,
            "ask": price + spread,
            "bid_depth": round(bid_depth, 2),
            "ask_depth": round(ask_depth, 2),
        }

    events = [
        make_event(open_price, "buy", 0),
        make_event(high_price, "buy", 5),
        make_event(low_price, "sell", 10),
        make_event(close_price, "sell" if close_price < open_price else "buy", 15),
    ]

    return events


def normalize_decision(decision: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "mrs": decision.get("mrs", decision.get("market_risk_score")),
        "severity": decision.get("severity"),
        "action_bundle": decision.get(
            "action_bundle",
            decision.get("recommended_action"),
        ),
    }


def validate_decision(decision: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors = []
    normalized = normalize_decision(decision)

    severity = normalized["severity"]
    mrs = normalized["mrs"]
    action_bundle = normalized["action_bundle"]

    if severity not in VALID_SEVERITIES:
        errors.append(f"Invalid severity: {severity}")

    try:
        mrs_float = float(mrs)
        if math.isnan(mrs_float) or mrs_float < 0:
            errors.append(f"Invalid MRS: {mrs}")
    except (TypeError, ValueError):
        errors.append(f"MRS missing or non-numeric: {mrs}")

    if not action_bundle:
        errors.append("Missing action_bundle")

    if severity in EXPECTED_ACTIONS and action_bundle not in EXPECTED_ACTIONS[severity]:
        errors.append(f"Action {action_bundle} not aligned with severity {severity}")

    return len(errors) == 0, errors


def run_empirical_calibration() -> pd.DataFrame:
    rows = []

    for symbol in ASSETS:
        df = fetch_market_data(symbol)

        for i in range(2, len(df)):
            prior_row = df.iloc[i - 2]
            previous_row = df.iloc[i - 1]
            current_row = df.iloc[i]

            events = build_event_from_prior_bar(symbol, previous_row, prior_row)
            decision = compute_quant_decision(events)
            normalized = normalize_decision(decision)

            decision_valid, decision_errors = validate_decision(decision)

            mrs = normalized["mrs"]
            severity = normalized["severity"]
            action_bundle = normalized["action_bundle"]

            try:
                mrs_float = float(mrs)
            except (TypeError, ValueError):
                mrs_float = None

            forward_return_1d = calculate_return(
                float(current_row["Close"]),
                float(previous_row["Close"]),
            )

            rows.append(
                {
                    "asset": symbol,
                    "date": previous_row.name.isoformat(),
                    "mrs": mrs_float,
                    "severity": severity,
                    "action_bundle": action_bundle,
                    "decision_valid": decision_valid,
                    "decision_errors": decision_errors,
                    "forward_return_1d": forward_return_1d,
                    "forward_loss_1d": min(forward_return_1d, 0),
                    "abs_forward_return_1d": abs(forward_return_1d),
                    "event": events,
                }
            )

    return pd.DataFrame(rows)


def summarize_by_severity(df: pd.DataFrame) -> List[Dict[str, Any]]:
    summaries = []

    for severity in sorted(VALID_SEVERITIES):
        subset = df[df["severity"] == severity].copy()

        if subset.empty:
            summaries.append(
                {
                    "severity": severity,
                    "count": 0,
                    "note": "No observations classified in this severity.",
                }
            )
            continue

        mrs_values = subset["mrs"].dropna().tolist()
        forward_losses = subset["forward_loss_1d"].dropna().tolist()
        abs_returns = subset["abs_forward_return_1d"].dropna().tolist()

        summaries.append(
            {
                "severity": severity,
                "count": int(len(subset)),
                "mrs_min": round(min(mrs_values), 2) if mrs_values else None,
                "mrs_avg": round(mean(mrs_values), 2) if mrs_values else None,
                "mrs_max": round(max(mrs_values), 2) if mrs_values else None,
                "mrs_std": round(stdev(mrs_values), 2) if len(mrs_values) > 1 else 0.0,
                "avg_forward_loss_pct": round(mean(forward_losses) * 100, 4)
                if forward_losses
                else 0.0,
                "avg_abs_forward_return_pct": round(mean(abs_returns) * 100, 4)
                if abs_returns
                else 0.0,
                "valid_decision_rate": round(float(subset["decision_valid"].mean()), 4),
            }
        )

    return summaries


def compute_separation_report(df: pd.DataFrame) -> Dict[str, Any]:
    report = {}
    ordered = ["Normal", "Guarded", "Defensive", "Critical"]

    for low, high in zip(ordered[:-1], ordered[1:]):
        low_values = df[df["severity"] == low]["mrs"].dropna()
        high_values = df[df["severity"] == high]["mrs"].dropna()

        if low_values.empty or high_values.empty:
            report[f"{low}_vs_{high}"] = {"status": "INSUFFICIENT_DATA"}
            continue

        overlap = float((low_values.max() >= high_values.min()))

        report[f"{low}_vs_{high}"] = {
            "lower_class_max_mrs": round(float(low_values.max()), 2),
            "higher_class_min_mrs": round(float(high_values.min()), 2),
            "classes_overlap": bool(overlap),
            "separation_margin": round(float(high_values.min() - low_values.max()), 2),
        }

    return report


def perturbation_test(df: pd.DataFrame, sample_size: int = 100) -> Dict[str, Any]:
    sample = df.dropna(subset=["mrs"]).head(sample_size)

    stable_count = 0
    total = 0

    for _, row in sample.iterrows():
        events = [dict(event) for event in row["event"]]
        original_severity = row["severity"]

        for price_multiplier in [0.995, 1.005]:
            perturbed_events = []

            for event in events:
                perturbed = dict(event)
                perturbed["price"] = float(event["price"]) * price_multiplier
                perturbed["bid"] = float(event["bid"]) * price_multiplier
                perturbed["ask"] = float(event["ask"]) * price_multiplier
                perturbed_events.append(perturbed)

            decision = normalize_decision(compute_quant_decision(perturbed_events))
            total += 1

            if decision["severity"] == original_severity:
                stable_count += 1

    return {
        "sample_size": int(len(sample)),
        "perturbations": total,
        "severity_stability_rate": round(stable_count / total, 4) if total else 0.0,
    }


def generate_report(evidence: Dict[str, Any]) -> None:
    lines = [
        "# FlowPay Empirical MRS Calibration Report",
        "",
        "## Purpose",
        "",
        "This report validates MRS (Market Risk Score) and severity behavior on empirical market-derived events.",
        "",
        "## Important Scope",
        "",
        "This is not a live order-book calibration. It is an empirical sanity test using historical daily market bars transformed into prior-bar OHLC events.",
        "",
        "## What this addresses",
        "",
        "- Multi-asset calibration",
        "- Empirical data instead of only synthetic templates",
        "- MRS numeric validity",
        "- Severity taxonomy validity",
        "- Action/severity alignment",
        "- MRS class separation",
        "- Sensitivity to small perturbations",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(evidence["summary"], indent=2),
        "```",
        "",
        "## Severity Summary",
        "",
        "```json",
        json.dumps(evidence["severity_summary"], indent=2),
        "```",
        "",
        "## Separation Report",
        "",
        "```json",
        json.dumps(evidence["separation_report"], indent=2),
        "```",
        "",
        "## Perturbation Test",
        "",
        "```json",
        json.dumps(evidence["perturbation_test"], indent=2),
        "```",
        "",
        "## Issues",
        "",
    ]

    if evidence["issues"]:
        for issue in evidence["issues"]:
            lines.append(f"- {issue}")
    else:
        lines.append("- No major empirical calibration issues detected.")

    (OUTPUT_DIR / "flowpay_empirical_mrs_calibration_report.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def detect_issues(
    df: pd.DataFrame,
    separation: Dict[str, Any],
    perturbation: Dict[str, Any],
) -> List[str]:
    issues = []

    if df.empty:
        return ["No calibration records generated."]

    valid_rate = float(df["decision_valid"].mean())

    if valid_rate < 0.99:
        issues.append(f"Decision contract validity below target: {valid_rate:.2%}")

    missing_severities = [
        severity for severity in VALID_SEVERITIES if df[df["severity"] == severity].empty
    ]

    if missing_severities:
        issues.append(f"No empirical samples classified as: {missing_severities}")

    for pair, values in separation.items():
        if values.get("classes_overlap") is True:
            issues.append(f"MRS overlap detected between classes: {pair}")

    if perturbation["severity_stability_rate"] < 0.90:
        issues.append(
            f"Severity stability under small perturbations below target: "
            f"{perturbation['severity_stability_rate']:.2%}"
        )

    return issues


def main() -> None:
    print("\nFLOWPAY EMPIRICAL MRS CALIBRATION REPORT")
    print("=" * 80)

    df = run_empirical_calibration()

    severity_summary = summarize_by_severity(df)
    separation_report = compute_separation_report(df)
    perturbation = perturbation_test(df)

    issues = detect_issues(df, separation_report, perturbation)

    summary = {
        "validation_type": "empirical MRS calibration sanity report",
        "start_date": START_DATE,
        "end_date": END_DATE,
        "assets": ASSETS,
        "total_records": int(len(df)),
        "decision_valid_rate": round(float(df["decision_valid"].mean()), 4),
        "mrs_valid_rate": round(float(df["mrs"].notna().mean()), 4),
        "unique_severities_observed": sorted(df["severity"].dropna().unique().tolist()),
        "verdict": "PASS" if not issues else "FAIL",
    }

    evidence = {
        "summary": summary,
        "severity_summary": severity_summary,
        "separation_report": separation_report,
        "perturbation_test": perturbation,
        "issues": issues,
    }

    df.drop(columns=["event"]).to_csv(
        OUTPUT_DIR / "flowpay_empirical_mrs_calibration_records.csv",
        index=False,
    )

    with open(OUTPUT_DIR / "flowpay_empirical_mrs_calibration_summary.json", "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)

    generate_report(evidence)

    print(json.dumps(summary, indent=2))

    print("\nSaved:")
    print(OUTPUT_DIR / "flowpay_empirical_mrs_calibration_records.csv")
    print(OUTPUT_DIR / "flowpay_empirical_mrs_calibration_summary.json")
    print(OUTPUT_DIR / "flowpay_empirical_mrs_calibration_report.md")


if __name__ == "__main__":
    main()