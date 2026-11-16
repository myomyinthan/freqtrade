"""Turn Freqtrade trade exports into a reviewable research report and fill-cost stress table."""

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from zipfile import ZipFile

STRATEGY = "PersonalSpotBaseline"


def load_stats(path):
    if path.suffix == ".zip":
        with ZipFile(path) as archive:
            member = f"{path.stem}.json"
            with archive.open(member) as stream:
                return json.load(stream)["strategy"][STRATEGY]
    return json.loads(path.read_text(encoding="utf-8"))["strategy"][STRATEGY]


def buy_hold(dataset, settings, start, end, fee):
    import pandas as pd

    returns = {}
    for pair in settings["exchange"]["pair_whitelist"]:
        file = dataset / f"{pair.replace('/', '_')}-1h.feather"
        frame = pd.read_feather(file, columns=["date", "open", "close"])
        dates = pd.to_datetime(frame["date"], utc=True)
        candles = frame.loc[(dates >= start) & (dates < end)]
        if candles.empty:
            raise ValueError(f"no benchmark candles for {pair}")
        returns[pair] = float(candles.iloc[-1]["close"] / candles.iloc[0]["open"]) * (
            1 - fee
        ) / (1 + fee) - 1
    return {"equal_weight_net_return": mean(returns.values()), "net_return_by_pair": returns}


def summarize(stats):
    balance = float(stats["starting_balance"])
    equity = peak = balance
    drawdown = fees = turnover = position_hours = 0.0
    trades = sorted(stats["trades"], key=lambda trade: trade["close_timestamp"])
    profits = []
    by_month, by_quarter, by_pair = defaultdict(float), defaultdict(float), defaultdict(float)
    equity_curve, sides = [], []
    costs = dict.fromkeys((5, 10, 25, 50), 0.0)
    for trade in trades:
        entered = float(trade["open_rate"]) * float(trade["amount"])
        exited = float(trade["close_rate"]) * float(trade["amount"])
        entry_fee, exit_fee = float(trade["fee_open"]), float(trade["fee_close"])
        fees += entered * entry_fee + exited * exit_fee
        turnover += entered + exited
        for bps in costs:
            costs[bps] += bps / 10_000 * (entered * (1 + entry_fee) + exited * (1 - exit_fee))
        profit = float(trade["profit_abs"])
        profits.append(profit)
        end = datetime.fromisoformat(trade["close_date"])
        by_month[end.strftime("%Y-%m")] += profit
        by_quarter[f"{end.year}-Q{(end.month - 1) // 3 + 1}"] += profit
        by_pair[trade["pair"]] += profit
        start_ts, end_ts = trade["open_timestamp"], trade["close_timestamp"]
        position_hours += (end_ts - start_ts) / 3_600_000
        if end_ts > start_ts:
            sides.extend(((start_ts, 1), (end_ts, -1)))
        equity += profit
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
        equity_curve.append({"date": trade["close_date"], "realized_equity": equity})
    market_hours = 0.0
    positions = 0
    previous = 0
    for timestamp, delta in sorted(sides):
        if positions > 0:
            market_hours += (timestamp - previous) / 3_600_000
        positions += delta
        previous = timestamp
    positive = [p for p in profits if p > 0]
    negative = [p for p in profits if p < 0]
    total = sum(profits)
    return {
        "starting_wallet": balance, "net_profit": total, "net_return": total / balance,
        "trade_count": len(profits), "cash_net_return": 0, "estimated_quote_fees": fees,
        "turnover_quote": turnover, "average_trade_hours": position_hours / len(profits) if profits else None,
        "hours_in_market": market_hours, "position_hours": position_hours,
        "realized_equity_drawdown": drawdown, "realized_equity_curve": equity_curve,
        "engine_account_drawdown": stats.get("max_drawdown_account"),
        "expectancy_quote_per_trade": mean(profits) if profits else None,
        "win_rate": len(positive) / len(profits) if profits else None,
        "average_win": mean(positive) if positive else None,
        "average_loss": mean(negative) if negative else None,
        "profit_factor": sum(positive) / -sum(negative) if negative else None,
        "exit_reasons": dict(Counter(trade["exit_reason"] for trade in trades)),
        "net_profit_by_pair": dict(by_pair), "net_profit_by_month": dict(by_month),
        "net_profit_by_quarter": dict(by_quarter),
        "fill_cost_net_returns": {str(bps): (total - cost) / balance for bps, cost in costs.items()},
        "fill_cost_model": "Adverse basis points on each exported fill with unchanged sizing, "
                           "times, order feasibility and exit triggers.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--dataset", type=Path)
    args = parser.parse_args()
    stats = load_stats(args.archive)
    report = summarize(stats)
    if args.dataset:
        directory = args.archive.parent
        run = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        settings = json.loads((directory / "settings.json").read_text(encoding="utf-8"))
        start, end = (datetime.strptime(part + "+0000", "%Y%m%d%z")
                      for part in run["range_utc"].split("-"))
        report["buy_hold"] = buy_hold(args.dataset, settings, start, end, run["fee_per_side"])
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
