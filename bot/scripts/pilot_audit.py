"""Audit B17 paper-pilot continuity, 30d/30-trade progress, and fill/fee drift vs historical model."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean
import sys

BOT_DIR = Path(__file__).resolve().parents[1]
if str(BOT_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(BOT_DIR / "scripts"))

import paper_status
from preflight import BASELINE_DB_NAME, LOG_REL_PATH, PAPER_DIR, check_paper_paths

DB_PATH = PAPER_DIR / BASELINE_DB_NAME
LOG_PATH = PAPER_DIR / LOG_REL_PATH

DEFAULT_MODEL_FEE = 0.001
DEFAULT_TARGET_DAYS = 30.0
DEFAULT_TARGET_TRADES = 30
DEFAULT_MAX_HEARTBEAT_GAP_SECONDS = 180.0


def _parse_sql_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    parsed = datetime.fromisoformat(cleaned)
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _hour_floor_iso(ts: datetime) -> str:
    utc = ts.astimezone(timezone.utc)
    floored = utc.replace(minute=0, second=0, microsecond=0)
    return floored.isoformat()


def load_candle_opens(candle_dir: Path | None, pairs: set[str]) -> dict[str, dict[str, float]]:
    if candle_dir is None:
        return {}
    try:
        import pandas as pd
    except ImportError:
        return {}
    opens: dict[str, dict[str, float]] = {}
    for pair in sorted(pairs):
        feather = candle_dir / f"{pair.replace('/', '_')}-1h.feather"
        if not feather.is_file():
            continue
        frame = pd.read_feather(feather, columns=["date", "open"])
        dates = pd.to_datetime(frame["date"], utc=True)
        opens[pair] = {
            dt.to_pydatetime().replace(minute=0, second=0, microsecond=0).isoformat(): float(op)
            for dt, op in zip(dates, frame["open"])
        }
    return opens


def audit_uptime_continuity(
    log_lines: list[str],
    *,
    since_utc: datetime | None = None,
    now_utc: datetime | None = None,
    max_gap_seconds: float = DEFAULT_MAX_HEARTBEAT_GAP_SECONDS,
) -> dict:
    timestamps: list[datetime] = []
    clean_stops_in_window = 0
    for line in log_lines:
        hb = paper_status.HEARTBEAT_RE.match(line)
        if hb:
            ts = paper_status.parse_log_ts(hb.group("ts"))
            if since_utc is None or ts >= since_utc:
                timestamps.append(ts)
            continue
        if "Cleaning up modules ..." in line:
            prefix = line[:23]
            try:
                stop_ts = paper_status.parse_log_ts(prefix)
            except ValueError:
                stop_ts = None
            if stop_ts is not None and (since_utc is None or stop_ts >= since_utc):
                clean_stops_in_window += 1

    if not timestamps:
        return {
            "window_start_utc": since_utc.isoformat() if since_utc else None,
            "last_heartbeat_utc": None,
            "heartbeat_count": 0,
            "observed_span_days": 0.0,
            "uptime_gaps": [],
            "largest_gap_seconds": None,
            "stops_in_window": clean_stops_in_window,
            "continuous_claim_valid": False,
        }

    start_ts = since_utc if (since_utc and since_utc <= timestamps[0]) else timestamps[0]
    end_ts = now_utc if (now_utc and now_utc >= timestamps[-1]) else timestamps[-1]

    gaps = []
    points = [start_ts, *timestamps]
    if now_utc is not None and now_utc > timestamps[-1]:
        points.append(now_utc)

    largest = 0.0
    for prev, curr in zip(points, points[1:]):
        delta = (curr - prev).total_seconds()
        if delta > largest:
            largest = delta
        if delta > max_gap_seconds:
            gaps.append({
                "from_utc": prev.isoformat(),
                "to_utc": curr.isoformat(),
                "gap_seconds": round(delta, 2),
            })

    span_days = max(0.0, (end_ts - start_ts).total_seconds() / 86400.0)
    return {
        "window_start_utc": start_ts.isoformat(),
        "last_heartbeat_utc": timestamps[-1].isoformat(),
        "heartbeat_count": len(timestamps),
        "observed_span_days": round(span_days, 4),
        "uptime_gaps": gaps,
        "largest_gap_seconds": round(largest, 2),
        "stops_in_window": clean_stops_in_window,
        "continuous_claim_valid": (len(gaps) == 0 and clean_stops_in_window == 0),
    }


def audit_paper_vs_model(
    db_path: Path,
    *,
    model_fee_per_side: float = DEFAULT_MODEL_FEE,
    strategy_filter: str | None = None,
    candle_opens: dict[str, dict[str, float]] | None = None,
) -> dict:
    if not db_path.is_file():
        return {
            "ledger_present": False,
            "natural_closed_trades": 0,
            "open_trades": 0,
            "force_entry_trades": 0,
            "strategies_seen": [],
            "enter_tags": {},
            "exit_reasons": {},
            "fee_comparison": None,
            "execution_drift_bps": None,
            "order_outcomes": {},
        }

    with closing(paper_status.connect_readonly(db_path)) as db:
        query = (
            "SELECT id, pair, is_open, fee_open, fee_close, open_rate, open_rate_requested, "
            "close_rate, close_rate_requested, close_profit_abs, stake_amount, amount, "
            "open_date, close_date, stop_loss, exit_reason, strategy, enter_tag "
            "FROM trades"
        )
        params: tuple = ()
        if strategy_filter:
            query += " WHERE strategy = ?"
            params = (strategy_filter,)
        trades = db.execute(query, params).fetchall()

        order_rows = db.execute(
            "SELECT ft_trade_id, ft_order_side, status, ft_cancel_reason FROM orders"
        ).fetchall()

    trade_ids = {row[0] for row in trades}
    filtered_orders = [row for row in order_rows if row[0] in trade_ids] if strategy_filter else order_rows

    strategies_seen = sorted({str(row[16]) for row in trades if row[16]})
    enter_tags: Counter[str] = Counter()
    exit_reasons: Counter[str] = Counter()
    force_entries = 0
    open_count = 0
    natural_closed = 0
    realized_net_pnl = 0.0

    fee_drifts_bps: list[float] = []
    req_entry_drifts_bps: list[float] = []
    req_exit_drifts_bps: list[float] = []
    candle_entry_drifts_bps: list[float] = []
    candle_exit_drifts_bps: list[float] = []
    candle_lookup = candle_opens or {}

    for row in trades:
        (
            _tid, pair, is_open, fee_open, fee_close, open_rate, open_req,
            close_rate, close_req, close_profit_abs, _stake, _amt,
            open_date_raw, close_date_raw, stop_loss, exit_reason, _strat, enter_tag,
        ) = row
        tag = str(enter_tag or "untagged")
        enter_tags[tag] += 1
        if tag == "force_entry":
            force_entries += 1

        if fee_open is not None:
            fee_drifts_bps.append((float(fee_open) - model_fee_per_side) * 10_000.0)
        if open_rate and open_req and float(open_req) > 0:
            # Long buy: paying above requested limit is positive adverse drift.
            req_entry_drifts_bps.append((float(open_rate) / float(open_req) - 1.0) * 10_000.0)

        open_dt = _parse_sql_utc(open_date_raw)
        if open_dt and open_rate and pair in candle_lookup:
            ref_open = candle_lookup[pair].get(_hour_floor_iso(open_dt))
            if ref_open and ref_open > 0:
                candle_entry_drifts_bps.append((float(open_rate) / ref_open - 1.0) * 10_000.0)

        if is_open:
            open_count += 1
            continue

        if tag != "force_entry":
            natural_closed += 1
        if close_profit_abs is not None:
            realized_net_pnl += float(close_profit_abs)
        reason = str(exit_reason or "unknown")
        exit_reasons[reason] += 1
        if fee_close is not None:
            fee_drifts_bps.append((float(fee_close) - model_fee_per_side) * 10_000.0)
        if close_rate and close_req and float(close_req) > 0:
            # Long sell: receiving below requested exit rate is positive adverse drift.
            req_exit_drifts_bps.append((1.0 - float(close_rate) / float(close_req)) * 10_000.0)

        close_dt = _parse_sql_utc(close_date_raw)
        if close_dt and close_rate:
            if reason == "stop_loss" and stop_loss and float(stop_loss) > 0:
                candle_exit_drifts_bps.append((1.0 - float(close_rate) / float(stop_loss)) * 10_000.0)
            elif pair in candle_lookup:
                ref_close = candle_lookup[pair].get(_hour_floor_iso(close_dt))
                if ref_close and ref_close > 0:
                    candle_exit_drifts_bps.append((1.0 - float(close_rate) / ref_close) * 10_000.0)

    status_counts = Counter(str(row[2] or "unknown") for row in filtered_orders)
    cancel_reasons = Counter(str(row[3]) for row in filtered_orders if row[3])

    def _stats(values: list[float]) -> dict | None:
        if not values:
            return None
        return {
            "samples": len(values),
            "mean_adverse_bps": round(mean(values), 3),
            "max_adverse_bps": round(max(values), 3),
            "min_adverse_bps": round(min(values), 3),
        }

    return {
        "ledger_present": True,
        "natural_closed_trades": natural_closed,
        "open_trades": open_count,
        "force_entry_trades": force_entries,
        "realized_net_profit_quote": round(realized_net_pnl, 6),
        "strategies_seen": strategies_seen,
        "enter_tags": dict(enter_tags),
        "exit_reasons": dict(exit_reasons),
        "fee_comparison": {
            "modeled_fee_per_side": model_fee_per_side,
            "observed_fee_drift_bps": _stats(fee_drifts_bps),
        },
        "execution_drift_bps": {
            "entry_vs_requested_rate": _stats(req_entry_drifts_bps),
            "exit_vs_requested_rate": _stats(req_exit_drifts_bps),
            "entry_vs_1h_candle_open": _stats(candle_entry_drifts_bps),
            "exit_vs_modeled_boundary_or_stop": _stats(candle_exit_drifts_bps),
        },
        "order_outcomes": {
            "by_status": dict(status_counts),
            "cancel_reasons": dict(cancel_reasons),
        },
    }


def evaluate_b17_gate(
    *,
    continuity: dict,
    execution: dict,
    active_alerts: list[dict],
    target_days: float = DEFAULT_TARGET_DAYS,
    target_trades: int = DEFAULT_TARGET_TRADES,
) -> dict:
    anomalies = []
    if execution.get("force_entry_trades", 0) > 0:
        anomalies.append("force_entry_detected_invalidates_natural_trade_sample")
    if not continuity.get("continuous_claim_valid", False):
        anomalies.append("uptime_gap_or_stop_detected_in_observation_window")
    if active_alerts:
        anomalies.append("active_operational_alerts_present")

    days_obs = float(continuity.get("observed_span_days") or 0.0)
    trades_obs = int(execution.get("natural_closed_trades") or 0)
    days_met = days_obs >= target_days
    trades_met = trades_obs >= target_trades

    if anomalies:
        verdict = "continuity_or_safety_exception_review_required"
    elif days_met and trades_met:
        verdict = "b17_minimum_observation_met_ready_for_b21_dossier"
    else:
        verdict = "observing_in_progress"

    return {
        "verdict": verdict,
        "target_continuous_days": target_days,
        "observed_continuous_days": round(days_obs, 4),
        "remaining_days": round(max(0.0, target_days - days_obs), 4),
        "target_natural_closed_trades": target_trades,
        "observed_natural_closed_trades": trades_obs,
        "remaining_natural_trades": max(0, target_trades - trades_obs),
        "anomalies": anomalies,
        "live_authorization_note": (
            "Passing B17 validates dry-run operation under simulated fills only; "
            "live trading still requires separate explicit user authorization."
        ),
    }


def run_pilot_audit(
    *,
    db_path: Path = DB_PATH,
    log_path: Path = LOG_PATH,
    candle_dir: Path | None = None,
    strategy_filter: str | None = None,
    since_utc: datetime | None = None,
    model_fee_per_side: float = DEFAULT_MODEL_FEE,
    target_days: float = DEFAULT_TARGET_DAYS,
    target_trades: int = DEFAULT_TARGET_TRADES,
    max_gap_seconds: float = DEFAULT_MAX_HEARTBEAT_GAP_SECONDS,
) -> dict:
    live = paper_status.status()
    effective_since = since_utc
    if effective_since is None and live.get("container_started"):
        effective_since = paper_status.parse_utc_iso(str(live["container_started"]))

    lines = (
        log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if log_path.is_file()
        else []
    )
    now_utc = datetime.now(timezone.utc) if live.get("container_state") == "running" else None
    continuity = audit_uptime_continuity(
        lines,
        since_utc=effective_since,
        now_utc=now_utc,
        max_gap_seconds=max_gap_seconds,
    )

    pairs: set[str] = set()
    if db_path.is_file():
        with closing(paper_status.connect_readonly(db_path)) as db:
            pairs = {row[0] for row in db.execute("SELECT DISTINCT pair FROM trades").fetchall() if row[0]}
    opens = load_candle_opens(candle_dir, pairs)
    execution = audit_paper_vs_model(
        db_path,
        model_fee_per_side=model_fee_per_side,
        strategy_filter=strategy_filter,
        candle_opens=opens,
    )
    gate = evaluate_b17_gate(
        continuity=continuity,
        execution=execution,
        active_alerts=live.get("alerts", []),
        target_days=target_days,
        target_trades=target_trades,
    )
    return {
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "container_state": live.get("container_state"),
        "active_strategy": (live.get("live_api") or {}).get("strategy"),
        "guard_enforcement": live.get("guard_enforcement"),
        "b17_gate": gate,
        "continuity": continuity,
        "execution_vs_historical_model": execution,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--log", type=Path, default=LOG_PATH)
    parser.add_argument("--candle-dir", type=Path, default=None)
    parser.add_argument("--strategy", default=None)
    parser.add_argument("--since-utc", default=None, help="ISO-8601 UTC start of pilot observation window")
    parser.add_argument("--model-fee", type=float, default=DEFAULT_MODEL_FEE)
    parser.add_argument("--target-days", type=float, default=DEFAULT_TARGET_DAYS)
    parser.add_argument("--target-trades", type=int, default=DEFAULT_TARGET_TRADES)
    parser.add_argument("--max-gap-seconds", type=float, default=DEFAULT_MAX_HEARTBEAT_GAP_SECONDS)
    args = parser.parse_args()

    try:
        check_paper_paths("PersonalSpotBaseline")
        since = paper_status.parse_utc_iso(args.since_utc) if args.since_utc else None
        report = run_pilot_audit(
            db_path=args.db,
            log_path=args.log,
            candle_dir=args.candle_dir,
            strategy_filter=args.strategy,
            since_utc=since,
            model_fee_per_side=args.model_fee,
            target_days=args.target_days,
            target_trades=args.target_trades,
            max_gap_seconds=args.max_gap_seconds,
        )
        print(json.dumps(report, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(f"Pilot audit failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
