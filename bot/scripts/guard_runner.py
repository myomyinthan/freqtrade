"""Separate persisted daily entry-halt polling and enforcement service for Milestone 4."""

from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parents[1]
for extra in (BOT_DIR / "scripts", BOT_DIR / "risk"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import paper_status
from guard import FlowEvent, Guard, snapshot_from_paper_sqlite
from preflight import (
    BASELINE_DB_NAME,
    GUARD_POLICY_NAME,
    GUARD_STATE_NAME,
    PAPER_DIR,
    _check_regular_unlinked,
    check_paper_paths,
    read_settings,
    reject_environment_overrides,
    resolve_config,
)

FLOWS_FILE_NAME = "guard.flows.json"
DEFAULT_POLL_INTERVAL = 10.0
DEFAULT_MAX_AGE = 30.0
DEFAULT_FEE_RATE = Decimal("0.001")


def account_id(config: dict) -> str:
    return f"paper:{config['exchange']['name']}:{config['stake_currency']}"


def policy_path() -> Path:
    return PAPER_DIR / GUARD_POLICY_NAME


def state_path() -> Path:
    return PAPER_DIR / GUARD_STATE_NAME


def flows_path() -> Path:
    return PAPER_DIR / FLOWS_FILE_NAME


def write_policy(
    config: dict,
    max_loss_quote: Decimal,
    max_age_seconds: float,
    poll_interval_seconds: float,
    exit_fee_rate: Decimal,
    max_loss_ratio: Decimal | None = None,
) -> dict:
    if max_loss_quote <= 0 or max_age_seconds <= 0 or poll_interval_seconds <= 0:
        raise ValueError("max_loss_quote, max_age_seconds and poll_interval_seconds must be positive")
    if poll_interval_seconds >= max_age_seconds:
        raise ValueError("poll_interval_seconds must be smaller than max_age_seconds")
    PAPER_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = policy_path()
    _check_regular_unlinked(path, "paper runtime control files")
    payload = {
        "version": 1,
        "mode": "paper",
        "account": account_id(config),
        "exchange": config["exchange"]["name"],
        "quote_currency": config["stake_currency"],
        "pairs": list(config["exchange"]["pair_whitelist"]),
        "starting_wallet_quote": str(config["dry_run_wallet"]),
        "max_loss_quote": str(max_loss_quote),
        "max_loss_ratio": str(max_loss_ratio) if max_loss_ratio is not None else None,
        "max_age_seconds": float(max_age_seconds),
        "poll_interval_seconds": float(poll_interval_seconds),
        "default_exit_fee_rate": str(exit_fee_rate),
    }
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    return payload


def load_policy(config: dict | None = None) -> tuple[dict, Guard]:
    path = policy_path()
    _check_regular_unlinked(path, "paper runtime control files")
    if not path.is_file():
        raise ValueError("guard.policy.json not found; run guard_runner.py init first")
    with path.open(encoding="utf-8") as stream:
        policy = read_settings(stream)
    if config is not None and policy.get("account") != account_id(config):
        raise ValueError("guard.policy.json account does not match settings")
    ratio = policy.get("max_loss_ratio")
    guard = Guard(
        path=state_path(),
        account=str(policy["account"]),
        max_loss=Decimal(str(policy["max_loss_quote"])),
        max_age=timedelta(seconds=float(policy["max_age_seconds"])),
        max_loss_ratio=Decimal(str(ratio)) if ratio is not None else None,
    )
    return policy, guard


def load_flow_events() -> list[FlowEvent]:
    path = flows_path()
    _check_regular_unlinked(path, "paper runtime control files")
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return [FlowEvent("invalid_flows_format", datetime.now(timezone.utc), None)]
    events = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            events.append(FlowEvent(f"invalid-{idx}", datetime.now(timezone.utc), None))
            continue
        ts_raw = str(item.get("timestamp", ""))
        ts = paper_status.parse_utc_iso(ts_raw) if ts_raw else datetime.now(timezone.utc)
        delta_raw = item.get("quote_delta")
        delta = Decimal(str(delta_raw)) if delta_raw is not None else None
        events.append(FlowEvent(str(item.get("event_id", "")), ts, delta))
    return events


def fetch_executable_bid_marks(exchange_name: str, pairs: list[str]) -> dict[str, Decimal]:
    if not pairs:
        return {}
    if exchange_name == "binance":
        symbols = json.dumps([pair.replace("/", "") for pair in pairs], separators=(",", ":"))
        url = "https://api.binance.com/api/v3/ticker/bookTicker?symbols=" + urllib.parse.quote(symbols)
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
        by_symbol = {row["symbol"]: Decimal(str(row["bidPrice"])) for row in rows if "bidPrice" in row}
        marks = {}
        for pair in pairs:
            sym = pair.replace("/", "")
            if sym in by_symbol and by_symbol[sym] > 0:
                marks[pair] = by_symbol[sym]
        return marks

    # Generic fallback via pinned container CCXT public fetch_tickers when non-Binance venue is configured.
    with (BOT_DIR / "VERSION.lock.json").open(encoding="utf-8") as stream:
        lock = read_settings(stream)
    code = (
        "import ccxt, json, sys\n"
        "spec = json.loads(sys.stdin.read())\n"
        "ex = getattr(ccxt, spec['exchange'])({'enableRateLimit': True})\n"
        "tickers = ex.fetch_tickers(spec['pairs'])\n"
        "out = {p: str(t.get('bid') or 0) for p, t in tickers.items()}\n"
        "print(json.dumps(out))\n"
    )
    proc = subprocess.run(
        ["docker", "run", "--rm", "-i", "--platform", lock["platform"], "--entrypoint", "python", lock["image"], "-c", code],
        input=json.dumps({"exchange": exchange_name, "pairs": pairs}),
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    parsed = json.loads(proc.stdout)
    return {pair: Decimal(val) for pair, val in parsed.items() if Decimal(val) > 0}


def required_open_pairs(db_path: Path) -> list[str]:
    if not db_path.is_file():
        return []
    with closing(paper_status.connect_readonly(db_path)) as db:
        rows = db.execute("SELECT DISTINCT pair FROM trades WHERE is_open AND amount > 0").fetchall()
    return sorted(row[0] for row in rows if row and row[0])


def collect_snapshot(policy: dict, db_path: Path, now: datetime | None = None, mark_fetcher=fetch_executable_bid_marks):
    observed = now or datetime.now(timezone.utc)
    open_pairs = required_open_pairs(db_path)
    marks: dict[str, Decimal] = {}
    if open_pairs:
        try:
            marks = mark_fetcher(str(policy["exchange"]), open_pairs)
        except Exception:
            marks = {}
    return snapshot_from_paper_sqlite(
        db_path=db_path,
        account=str(policy["account"]),
        observed_at=observed,
        starting_wallet=Decimal(str(policy["starting_wallet_quote"])),
        quote_currency=str(policy["quote_currency"]),
        executable_bid_marks=marks,
        default_exit_fee_rate=Decimal(str(policy["default_exit_fee_rate"])),
        flow_events=load_flow_events(),
    )


def enforce_halt(guard: Guard, now: datetime | None = None, pause_fn=paper_status.pause_entries) -> dict:
    started_ns = time.monotonic_ns()
    current = now or datetime.now(timezone.utc)
    try:
        result = pause_fn()
        elapsed_ms = (time.monotonic_ns() - started_ns) / 1_000_000.0
        remaining = () if int(result.get("remaining_open_entry_orders", 0)) == 0 else ("unreconciled_entry",)
        return guard.record_enforcement(
            current,
            api_paused=(str(result.get("verified_state", "")).lower() == "paused"),
            remaining_pending_entries=remaining,
            detail="api_paused_and_entries_reconciled",
            latency_ms=elapsed_ms,
        )
    except Exception as exc:
        elapsed_ms = (time.monotonic_ns() - started_ns) / 1_000_000.0
        state = guard._read()
        existing = tuple(state.get("pending_entries", ())) or tuple(state.get("pending_cancellations", ()))
        return guard.record_enforcement(
            current,
            api_paused=False,
            remaining_pending_entries=existing,
            detail=f"api_enforcement_deferred:{paper_status.sanitize_text(str(exc))}",
            latency_ms=elapsed_ms,
        )


def poll_once(
    policy: dict,
    guard: Guard,
    db_path: Path = PAPER_DIR / BASELINE_DB_NAME,
    mark_fetcher=fetch_executable_bid_marks,
    pause_fn=paper_status.pause_entries,
) -> dict:
    poll_started_ns = time.monotonic_ns()
    now = datetime.now(timezone.utc)
    snapshot = collect_snapshot(policy, db_path, now=now, mark_fetcher=mark_fetcher)
    state = guard.observe(snapshot, now)
    if state["latch"] is not None and (state.get("enforcement_pending") or state.get("pending_entries")):
        state = enforce_halt(guard, now=datetime.now(timezone.utc), pause_fn=pause_fn)
    poll_ms = round((time.monotonic_ns() - poll_started_ns) / 1_000_000.0, 2)
    return {
        "timestamp": now.isoformat(),
        "entries_allowed": guard.entries_allowed(datetime.now(timezone.utc)),
        "latch": state["latch"],
        "loss": state["loss"],
        "latest_equity": state.get("latest_equity"),
        "opening_equity": state.get("opening_equity"),
        "enforcement_pending": state.get("enforcement_pending"),
        "last_enforcement": state.get("last_enforcement"),
        "poll_latency_ms": poll_ms,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("init", "bootstrap-day", "poll-once", "watch", "halt", "rearm", "status"),
    )
    parser.add_argument("settings", type=Path)
    parser.add_argument("--max-loss-quote", type=Decimal, default=Decimal("25"))
    parser.add_argument("--max-loss-ratio", type=Decimal, default=None)
    parser.add_argument("--max-age-seconds", type=float, default=DEFAULT_MAX_AGE)
    parser.add_argument("--poll-interval-seconds", type=float, default=DEFAULT_POLL_INTERVAL)
    parser.add_argument("--exit-fee-rate", type=Decimal, default=DEFAULT_FEE_RATE)
    parser.add_argument("--reason", default="")
    parser.add_argument("--iterations", type=int, default=0, help="bounded loop count for drills/tests (0 = infinite)")
    args = parser.parse_args()

    try:
        reject_environment_overrides()
        with args.settings.open(encoding="utf-8") as stream:
            settings = read_settings(stream)
        config = resolve_config(settings, "PersonalSpotGuarded")
        check_paper_paths("PersonalSpotGuarded")
        db_path = PAPER_DIR / BASELINE_DB_NAME

        if args.action == "init":
            policy = write_policy(
                config=config,
                max_loss_quote=args.max_loss_quote,
                max_age_seconds=args.max_age_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
                exit_fee_rate=args.exit_fee_rate,
                max_loss_ratio=args.max_loss_ratio,
            )
            print(json.dumps(policy, indent=2))
            return 0

        policy, guard = load_policy(config)
        if args.action == "bootstrap-day":
            now = datetime.now(timezone.utc)
            snap = collect_snapshot(policy, db_path, now=now)
            state = guard.bootstrap_day_baseline(snap, now, args.reason)
            print(json.dumps({
                "account": state["account"],
                "utc_day": state["utc_day"],
                "opening_equity": state["opening_equity"],
                "latch": state["latch"],
                "entries_allowed": guard.entries_allowed(datetime.now(timezone.utc)),
            }, indent=2))
            return 0

        if args.action == "poll-once":
            print(json.dumps(poll_once(policy, guard, db_path=db_path), indent=2))
            return 0

        if args.action == "watch":
            interval = float(policy["poll_interval_seconds"])
            count = 0
            last_monotonic = time.monotonic()
            while True:
                now_mono = time.monotonic()
                # Detect host monotonic sleep/freeze gaps exceeding max_age_seconds.
                if count > 0 and (now_mono - last_monotonic) > float(policy["max_age_seconds"]):
                    guard.latch_manual(datetime.now(timezone.utc), "monotonic_clock_or_sleep_gap")
                last_monotonic = now_mono
                summary = poll_once(policy, guard, db_path=db_path)
                print(json.dumps(summary), flush=True)
                count += 1
                if args.iterations and count >= args.iterations:
                    return 0
                elapsed = time.monotonic() - now_mono
                time.sleep(max(0.1, interval - elapsed))

        if args.action == "halt":
            now = datetime.now(timezone.utc)
            guard.latch_manual(now, args.reason)
            state = enforce_halt(guard, now=datetime.now(timezone.utc))
            print(json.dumps({
                "latch": state["latch"],
                "entries_allowed": guard.entries_allowed(datetime.now(timezone.utc)),
                "enforcement_pending": state["enforcement_pending"],
                "last_enforcement": state["last_enforcement"],
            }, indent=2))
            return 0

        if args.action == "rearm":
            # Observe a fresh reconciled snapshot first so rearm validates live state.
            poll_once(policy, guard, db_path=db_path)
            now = datetime.now(timezone.utc)
            guard.rearm(now, args.reason)
            print(json.dumps({
                "latch": None,
                "entries_allowed": guard.entries_allowed(datetime.now(timezone.utc)),
            }, indent=2))
            return 0

        if args.action == "status":
            state = guard._read() if state_path().is_file() else None
            print(json.dumps({
                "policy": policy,
                "entries_allowed": guard.entries_allowed(datetime.now(timezone.utc)),
                "state": state,
            }, indent=2))
            return 0

        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"Guard runner failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
