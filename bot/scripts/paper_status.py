"""Inspect, monitor, pause/reconcile, back up, restore-test and export paper operations."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from preflight import (
    API_AUTH_NAME,
    BASELINE_DB_NAME,
    GUARD_POLICY_NAME,
    GUARD_STATE_NAME,
    LOG_REL_PATH,
    PAPER_DIR,
    check_paper_paths,
    read_settings,
)

CONTAINER_NAME = "personalspot-paper-runner"
BASELINE = "PersonalSpotBaseline"
DB = PAPER_DIR / BASELINE_DB_NAME
LOG_FILE = PAPER_DIR / LOG_REL_PATH
API_AUTH = PAPER_DIR / API_AUTH_NAME
GUARD_POLICY = PAPER_DIR / GUARD_POLICY_NAME
GUARD_STATE = PAPER_DIR / GUARD_STATE_NAME
BACKUP_DIR = PAPER_DIR / "backups"

DEFAULT_MAX_HEARTBEAT_AGE = 120.0
DEFAULT_MAX_CANDLE_AGE = 7200.0
DEFAULT_MIN_FREE_BYTES = 1024 * 1024 * 1024
DEFAULT_ERROR_THRESHOLD = 3
DEFAULT_KEEP_DAILY_BACKUPS = 7
DEFAULT_KEEP_WEEKLY_BACKUPS = 4

MANAGED_BACKUP_RE = re.compile(r"^paper-(?P<stamp>\d{8}T\d{6}Z)\.sqlite$")

HEARTBEAT_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - .* - INFO - "
    r"Bot heartbeat\. PID=\d+, version='[^']+', state='(?P<state>[A-Z_]+)'"
)
ERROR_LINE_RE = re.compile(r" - (?:ERROR|CRITICAL) - ")
STATE_CHANGE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - .* - INFO - "
    r"Changing state(?: from [A-Z_]+)? to: (?P<state>[A-Z_]+)"
)

REDACT_KEYS = {
    "password", "jwt_secret_key", "ws_token", "secret", "key", "api_key",
    "token", "access_token", "refresh_token", "authorization",
}
REDACT_PATTERNS = (
    (re.compile(r"(?i)(authorization\s*[:=]\s*(?:basic|bearer)\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:password|jwt_secret_key|ws_token|secret|api_key|token)\s*['\"]?\s*[:=]\s*['\"]?)[^'\",\s}]+"), r"\1[REDACTED]"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_utc_iso(value: str) -> datetime:
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    parsed = datetime.fromisoformat(cleaned)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_log_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=timezone.utc)


def sanitize_text(text: str) -> str:
    cleaned = text
    for pattern, replacement in REDACT_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


def sanitize_value(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if str(key).lower() in REDACT_KEYS:
                result[key] = "[REDACTED]"
            else:
                result[key] = sanitize_value(item)
        return result
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ValueError(f"SQLite ledger is unavailable: {path.name}")
    uri = path.absolute().as_uri()
    try:
        conn = sqlite3.connect(uri + "?mode=ro", uri=True)
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
        return conn
    except sqlite3.OperationalError:
        wal = Path(str(path) + "-wal")
        if wal.exists() and wal.stat().st_size > 0:
            raise
        return sqlite3.connect(uri + "?mode=ro&immutable=1", uri=True)


def ledger(path: Path) -> dict[str, int]:
    with closing(connect_readonly(path)) as db:
        return {
            "open_positions": db.execute("SELECT count(*) FROM trades WHERE is_open").fetchone()[0],
            "closed_positions": db.execute("SELECT count(*) FROM trades WHERE NOT is_open").fetchone()[0],
            "pending_orders": db.execute("SELECT count(*) FROM orders WHERE ft_is_open").fetchone()[0],
        }


def order_side_breakdown(path: Path) -> dict[str, int] | None:
    if not path.is_file():
        return None
    with closing(connect_readonly(path)) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(orders)").fetchall()}
        if "ft_order_side" not in columns:
            return None
        entries = db.execute(
            "SELECT count(*) FROM orders WHERE ft_is_open AND ft_order_side = 'buy'"
        ).fetchone()[0]
        exits = db.execute(
            "SELECT count(*) FROM orders WHERE ft_is_open AND ft_order_side = 'sell'"
        ).fetchone()[0]
        return {"pending_entry_orders": entries, "pending_exit_orders": exits}


def backup(destination: Path, source_db: Path | None = None) -> None:
    live_db = DB if source_db is None else source_db
    with closing(connect_readonly(live_db)) as source:
        # Reserve the filename so repeated or concurrent backups cannot replace a prior backup.
        destination.touch(mode=0o600, exist_ok=False)
        try:
            with closing(sqlite3.connect(destination)) as copy:
                source.backup(copy)
                copy.execute("PRAGMA journal_mode=DELETE")
                if copy.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise ValueError("backup failed SQLite quick_check")
        except Exception:
            destination.unlink(missing_ok=True)
            raise


def list_managed_backups(backup_dir: Path = BACKUP_DIR) -> list[tuple[datetime, Path]]:
    if not backup_dir.is_dir():
        return []
    if backup_dir.is_symlink():
        raise ValueError("backup directory must not be a symlink")
    found = []
    for item in backup_dir.iterdir():
        match = MANAGED_BACKUP_RE.match(item.name)
        if not match or item.is_symlink() or not item.is_file():
            continue
        stamp = datetime.strptime(match.group("stamp"), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        found.append((stamp, item))
    found.sort(key=lambda pair: pair[0], reverse=True)
    return found


def prune_managed_backups(
    backup_dir: Path = BACKUP_DIR,
    keep_daily: int = DEFAULT_KEEP_DAILY_BACKUPS,
    keep_weekly: int = DEFAULT_KEEP_WEEKLY_BACKUPS,
) -> dict:
    if keep_daily < 1 or keep_weekly < 0:
        raise ValueError("keep_daily must be >= 1 and keep_weekly >= 0")
    snapshots = list_managed_backups(backup_dir)
    if not snapshots:
        return {"backup_dir": str(backup_dir), "kept": [], "pruned": []}

    with closing(connect_readonly(snapshots[0][1])) as latest_conn:
        if latest_conn.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("newest managed backup failed quick_check; aborting retention prune")

    keep_names: set[str] = {snapshots[0][1].name}
    daily_days = set()
    weekly_weeks = set()
    for stamp, path in snapshots:
        day_key = stamp.date()
        if len(daily_days) < keep_daily and day_key not in daily_days:
            daily_days.add(day_key)
            keep_names.add(path.name)
        iso = stamp.isocalendar()
        week_key = (iso.year, iso.week)
        if len(weekly_weeks) < keep_weekly and week_key not in weekly_weeks:
            weekly_weeks.add(week_key)
            keep_names.add(path.name)

    kept, pruned = [], []
    for _, path in snapshots:
        if path.name in keep_names:
            kept.append(path.name)
        else:
            stem = path.name[:-len(".sqlite")]
            for candidate in (
                path,
                backup_dir / f"{stem}.meta.json",
                backup_dir / f"{path.name}-shm",
                backup_dir / f"{path.name}-wal",
            ):
                candidate.unlink(missing_ok=True)
            pruned.append(path.name)

    return {"backup_dir": str(backup_dir), "kept": kept, "pruned": pruned}


def snapshot_and_rotate_backups(
    backup_dir: Path = BACKUP_DIR,
    keep_daily: int = DEFAULT_KEEP_DAILY_BACKUPS,
    keep_weekly: int = DEFAULT_KEEP_WEEKLY_BACKUPS,
    source_db: Path | None = None,
    now: datetime | None = None,
) -> dict:
    live_db = DB if source_db is None else source_db
    if backup_dir.is_symlink():
        raise ValueError("backup directory must not be a symlink")
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp_dt = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = stamp_dt.strftime("%Y%m%dT%H%M%SZ")
    sqlite_dest = backup_dir / f"paper-{stamp}.sqlite"
    meta_dest = backup_dir / f"paper-{stamp}.meta.json"

    backup(sqlite_dest, source_db=live_db)
    meta_payload = sanitize_value({
        "created_at_utc": stamp_dt.isoformat(),
        "sqlite_backup": sqlite_dest.name,
        "sqlite_sha256": sha256_file(sqlite_dest),
        "ledger": ledger(sqlite_dest),
        "order_sides": order_side_breakdown(sqlite_dest),
        "guard_health": inspect_guard(now=stamp_dt),
    })
    fd = os.open(meta_dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(meta_payload, stream, indent=2)
        stream.write("\n")

    retention = prune_managed_backups(backup_dir, keep_daily=keep_daily, keep_weekly=keep_weekly)
    return {
        "created_sqlite": str(sqlite_dest),
        "created_metadata": str(meta_dest),
        "sqlite_sha256": meta_payload["sqlite_sha256"],
        "retention": retention,
    }


def restore_drill(backup_path: Path, isolated_dir: Path, source_db: Path | None = None) -> dict:
    live_db = DB if source_db is None else source_db
    if not backup_path.is_file() or backup_path.is_symlink():
        raise ValueError("backup_path must be an existing regular file")
    resolved_paper = PAPER_DIR.resolve()
    resolved_target = isolated_dir.resolve()
    if resolved_target == resolved_paper or resolved_paper in resolved_target.parents:
        raise ValueError("isolated restore directory must be outside bot/runtime/paper")
    if isolated_dir.exists():
        raise ValueError("isolated restore directory must not already exist")

    before_sha = sha256_file(live_db) if live_db.is_file() else None
    isolated_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    restored_db = isolated_dir / "restored.paper.sqlite"
    with closing(connect_readonly(backup_path)) as src:
        restored_db.touch(mode=0o600, exist_ok=False)
        with closing(sqlite3.connect(restored_db)) as dst:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")

    with closing(connect_readonly(restored_db)) as check_db:
        integrity = check_db.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise ValueError(f"isolated restore failed integrity_check: {integrity}")
        tables = sorted(
            row[0]
            for row in check_db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        )
    if not {"trades", "orders"} <= set(tables):
        raise ValueError("restored SQLite database is missing required Freqtrade tables")

    summary = ledger(restored_db)
    sides = order_side_breakdown(restored_db)
    after_sha = sha256_file(live_db) if live_db.is_file() else None
    if before_sha != after_sha:
        raise ValueError("live paper database changed during isolated restore drill")
    return {
        "restored_path": str(restored_db),
        "integrity_check": "ok",
        "tables": tables,
        "ledger": summary,
        "order_sides": sides,
        "production_db_unchanged": True,
        "production_db_sha256": after_sha,
    }


def inspect_logs(log_path: Path = LOG_FILE, tail_lines: int = 200) -> dict:
    log_dir = log_path.parent
    rotated = []
    if log_dir.is_dir():
        for item in sorted(log_dir.glob(log_path.name + "*")):
            if item.is_file() and not item.is_symlink():
                rotated.append({"name": item.name, "size_bytes": item.stat().st_size})
    if not log_path.is_file():
        return {
            "log_present": False,
            "rotated_files": rotated,
            "last_heartbeat_utc": None,
            "last_heartbeat_state": None,
            "last_state_transition": None,
            "recent_error_count": 0,
            "startup_runs_logged": 0,
            "clean_stops_logged": 0,
            "tail": [],
        }

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    last_hb_ts = None
    last_hb_state = None
    last_state = None
    starts = 0
    stops = 0
    for line in lines:
        hb = HEARTBEAT_RE.match(line)
        if hb:
            last_hb_ts = parse_log_ts(hb.group("ts")).isoformat()
            last_hb_state = hb.group("state")
        st = STATE_CHANGE_RE.match(line)
        if st:
            last_state = st.group("state")
            if last_state in ("RUNNING", "PAUSED"):
                starts += 1
            elif last_state == "STOPPED":
                stops += 1
        elif "Cleaning up modules ..." in line:
            stops += 1

    window = lines[-tail_lines:]
    recent_errors = sum(1 for line in window if ERROR_LINE_RE.search(line))
    return {
        "log_present": True,
        "rotated_files": rotated,
        "last_heartbeat_utc": last_hb_ts,
        "last_heartbeat_state": last_hb_state,
        "last_state_transition": last_state,
        "recent_error_count": recent_errors,
        "startup_runs_logged": starts,
        "clean_stops_logged": stops,
        "tail": [sanitize_text(line) for line in lines[-25:]],
    }


def _container_api_call(
    method: str, path: str, auth: dict | None = None, payload: dict | None = None,
) -> tuple[int, object]:
    headers = {"Accept": "application/json"}
    if auth is not None:
        token = base64.b64encode(f"{auth['username']}:{auth['password']}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload)

    script = (
        "import json, sys, urllib.error, urllib.request\n"
        "req_in = json.loads(sys.stdin.read())\n"
        "data = req_in['body'].encode('utf-8') if req_in['body'] is not None else None\n"
        "req = urllib.request.Request(req_in['url'], data=data, headers=req_in['headers'], method=req_in['method'])\n"
        "try:\n"
        "    with urllib.request.urlopen(req, timeout=10) as resp:\n"
        "        raw = resp.read().decode('utf-8', errors='replace')\n"
        "        print(json.dumps({'status': resp.status, 'body': raw}))\n"
        "except urllib.error.HTTPError as exc:\n"
        "    raw = exc.read().decode('utf-8', errors='replace')\n"
        "    print(json.dumps({'status': exc.code, 'body': raw}))\n"
    )
    request_spec = {
        "method": method,
        "url": f"http://127.0.0.1:8080/api/v1{path}",
        "headers": headers,
        "body": body,
    }
    proc = subprocess.run(
        ["docker", "exec", "-i", CONTAINER_NAME, "python", "-c", script],
        input=json.dumps(request_spec),
        capture_output=True,
        text=True,
        check=True,
    )
    envelope = json.loads(proc.stdout)
    raw_body = envelope["body"]
    try:
        parsed = json.loads(raw_body) if raw_body else None
    except json.JSONDecodeError:
        parsed = raw_body
    return int(envelope["status"]), parsed


def load_api_auth(auth_path: Path = API_AUTH) -> dict:
    if not auth_path.is_file() or auth_path.is_symlink():
        raise ValueError("local API credentials are unavailable; start preflight with --local-api")
    with auth_path.open(encoding="utf-8") as stream:
        return read_settings(stream)


def probe_live_api(now: datetime | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    auth = load_api_auth()
    unauth_code, _ = _container_api_call("GET", "/show_config", auth=None)
    if unauth_code != 401:
        raise ValueError(f"local API failed authentication check: expected 401, got {unauth_code}")

    cfg_code, show_cfg = _container_api_call("GET", "/show_config", auth=auth)
    health_code, health = _container_api_call("GET", "/health", auth=auth)
    wl_code, whitelist = _container_api_call("GET", "/whitelist", auth=auth)
    if cfg_code != 200 or health_code != 200 or wl_code != 200 or not isinstance(show_cfg, dict):
        raise ValueError("authenticated local API health/config probe failed")

    pairs = whitelist.get("whitelist", []) if isinstance(whitelist, dict) else []
    timeframe = show_cfg.get("timeframe", "1h")
    candles = {}
    import urllib.parse

    for pair in pairs:
        query = urllib.parse.urlencode({"pair": pair, "timeframe": timeframe, "limit": 2})
        c_code, hist = _container_api_call("GET", f"/pair_candles?{query}", auth=auth)
        if c_code == 200 and isinstance(hist, dict) and hist.get("length", 0) > 0:
            close_ms = int(hist["data_stop_ts"]) + int(hist["timeframe_ms"])
            age_s = current.timestamp() - (close_ms / 1000.0)
            candles[pair] = {
                "rows_loaded": int(hist["length"]),
                "latest_candle_open_utc": hist.get("data_stop"),
                "completed_candle_age_seconds": round(age_s, 2),
            }
        else:
            candles[pair] = {"rows_loaded": 0, "latest_candle_open_utc": None, "completed_candle_age_seconds": None}

    return {
        "unauthenticated_http_status": unauth_code,
        "dry_run": show_cfg.get("dry_run"),
        "trading_mode": show_cfg.get("trading_mode"),
        "force_entry_enable": show_cfg.get("force_entry_enable"),
        "strategy": show_cfg.get("strategy"),
        "state": show_cfg.get("state"),
        "exchange": show_cfg.get("exchange"),
        "stake_currency": show_cfg.get("stake_currency"),
        "stake_amount": show_cfg.get("stake_amount"),
        "max_open_trades": show_cfg.get("max_open_trades"),
        "pairs": pairs,
        "last_process_ts": health.get("last_process_ts") if isinstance(health, dict) else None,
        "candles": candles,
    }


def _finite_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _pct_to_target(target: float | None, current: float | None) -> float | None:
    if target is None or current is None or current <= 0:
        return None
    return round((target / current - 1.0) * 100.0, 2)


def _pct_cushion_above(floor_val: float | None, current: float | None) -> float | None:
    if floor_val is None or current is None or floor_val <= 0:
        return None
    return round((current / floor_val - 1.0) * 100.0, 2)


def summarize_pair_signal_row(pair: str, strategy: str, row: dict) -> dict:
    close = _finite_float(row.get("close"))
    volume = _finite_float(row.get("volume"))
    warmed_up = bool(row.get("warmed_up"))
    base_info = {
        "pair": pair,
        "candle_open_utc": str(row.get("date")) if row.get("date") is not None else None,
        "close": round(close, 4) if close is not None else None,
        "warmed_up": warmed_up,
        "enter_long": int(row.get("enter_long") or 0),
        "exit_long": int(row.get("exit_long") or 0),
    }

    if strategy in ("PersonalSpotMacroBreakout", "PersonalSpotMacroBreakoutGuarded"):
        sma120 = _finite_float(row.get("sma120"))
        sma360 = _finite_float(row.get("sma360"))
        slope = _finite_float(row.get("sma360_slope24"))
        high336 = _finite_float(row.get("prior_high_336"))
        low96 = _finite_float(row.get("prior_low_96"))
        vol24 = _finite_float(row.get("prior_vol_sma24"))
        conditions = {
            "warmed_up": warmed_up,
            "above_sma120": bool(close is not None and sma120 is not None and close > sma120),
            "macro_sma_stacked": bool(sma120 is not None and sma360 is not None and sma120 > sma360),
            "macro_slope_rising": bool(slope is not None and slope > 0),
            "breakout_14d_high": bool(close is not None and high336 is not None and close > high336),
            "volume_above_24h_avg": bool(volume is not None and vol24 is not None and volume > 0 and volume > vol24),
        }
        regime = (
            "bull_macro_aligned"
            if (conditions["above_sma120"] and conditions["macro_sma_stacked"] and conditions["macro_slope_rising"])
            else "bear_or_neutral_cash"
        )
        met_count = sum(1 for passed in conditions.values() if passed)
        return {
            **base_info,
            "regime": regime,
            "entry_gates_passed": f"{met_count}/{len(conditions)}",
            "conditions": conditions,
            "levels": {
                "sma120": round(sma120, 4) if sma120 is not None else None,
                "sma360": round(sma360, 4) if sma360 is not None else None,
                "sma360_slope24": round(slope, 4) if slope is not None else None,
                "prior_high_336": round(high336, 4) if high336 is not None else None,
                "prior_low_96": round(low96, 4) if low96 is not None else None,
            },
            "proximity_pct": {
                "move_to_sma120_pct": _pct_to_target(sma120, close),
                "move_to_sma360_pct": _pct_to_target(sma360, close),
                "move_to_14d_breakout_pct": _pct_to_target(high336, close),
                "cushion_above_4d_exit_pct": _pct_cushion_above(low96, close),
            },
        }

    if strategy in ("PersonalSpotBreakout", "PersonalSpotBreakoutGuarded"):
        sma200 = _finite_float(row.get("sma200"))
        slope = _finite_float(row.get("sma200_slope24"))
        high168 = _finite_float(row.get("prior_high_168"))
        low72 = _finite_float(row.get("prior_low_72"))
        vol24 = _finite_float(row.get("prior_vol_sma24"))
        conditions = {
            "warmed_up": warmed_up,
            "above_sma200": bool(close is not None and sma200 is not None and close > sma200),
            "sma200_slope_rising": bool(slope is not None and slope > 0),
            "breakout_7d_high": bool(close is not None and high168 is not None and close > high168),
            "volume_above_24h_avg": bool(volume is not None and vol24 is not None and volume > 0 and volume > vol24),
        }
        regime = (
            "bull_macro_aligned"
            if (conditions["above_sma200"] and conditions["sma200_slope_rising"])
            else "bear_or_neutral_cash"
        )
        met_count = sum(1 for passed in conditions.values() if passed)
        return {
            **base_info,
            "regime": regime,
            "entry_gates_passed": f"{met_count}/{len(conditions)}",
            "conditions": conditions,
            "proximity_pct": {
                "move_to_sma200_pct": _pct_to_target(sma200, close),
                "move_to_7d_breakout_pct": _pct_to_target(high168, close),
                "cushion_above_3d_exit_pct": _pct_cushion_above(low72, close),
            },
        }

    sma20 = _finite_float(row.get("sma20"))
    sma50 = _finite_float(row.get("sma50"))
    return {
        **base_info,
        "regime": "sma20_above_sma50" if (sma20 is not None and sma50 is not None and sma20 > sma50) else "sma20_at_or_below_sma50",
        "proximity_pct": {
            "sma20_to_sma50_pct": _pct_to_target(sma50, sma20),
        },
    }


def probe_signal_proximity() -> dict:
    import urllib.parse

    auth = load_api_auth()
    cfg_code, show_cfg = _container_api_call("GET", "/show_config", auth=auth)
    wl_code, whitelist = _container_api_call("GET", "/whitelist", auth=auth)
    if cfg_code != 200 or wl_code != 200 or not isinstance(show_cfg, dict):
        raise ValueError("authenticated local API signal probe failed")
    strategy = str(show_cfg.get("strategy") or "")
    timeframe = str(show_cfg.get("timeframe") or "1h")
    pairs = whitelist.get("whitelist", []) if isinstance(whitelist, dict) else []
    summaries = {}
    for pair in pairs:
        query = urllib.parse.urlencode({"pair": pair, "timeframe": timeframe, "limit": 2})
        c_code, hist = _container_api_call("GET", f"/pair_candles?{query}", auth=auth)
        if c_code == 200 and isinstance(hist, dict) and hist.get("length", 0) > 0:
            cols = hist.get("columns", [])
            latest = dict(zip(cols, hist["data"][-1]))
            summaries[pair] = summarize_pair_signal_row(pair, strategy, latest)
        else:
            summaries[pair] = {"pair": pair, "warmed_up": False, "error": "no_candles_loaded"}
    return {
        "strategy": strategy,
        "timeframe": timeframe,
        "bot_state": show_cfg.get("state"),
        "pairs": summaries,
    }


def reconcile_pending_entries(open_trades: list[dict], cancel_order_fn, reload_trade_fn) -> dict:
    cancelled_entry_trades = []
    preserved_exit_trades = []
    reconciled_trade_ids = []
    for trade in open_trades:
        trade_id = int(trade["trade_id"])
        orders = [order for order in trade.get("orders", []) if order.get("is_open")]
        if not orders and not trade.get("has_open_orders"):
            continue
        sides = {order.get("ft_order_side") for order in orders}
        if sides == {"buy"}:
            cancel_order_fn(trade_id)
            cancelled_entry_trades.append(trade_id)
            reload_trade_fn(trade_id)
            reconciled_trade_ids.append(trade_id)
        else:
            preserved_exit_trades.append({
                "trade_id": trade_id,
                "pair": trade.get("pair"),
                "open_order_sides": sorted(str(side) for side in sides),
            })
    return {
        "cancelled_entry_trade_ids": cancelled_entry_trades,
        "reconciled_trade_ids": reconciled_trade_ids,
        "preserved_exit_trades": preserved_exit_trades,
    }


def pause_entries() -> dict:
    auth = load_api_auth()
    code, msg = _container_api_call("POST", "/pause", auth=auth)
    if code != 200:
        raise ValueError(f"pause endpoint failed with HTTP {code}: {msg}")
    st_code, open_trades = _container_api_call("GET", "/status", auth=auth)
    if st_code != 200 or not isinstance(open_trades, list):
        raise ValueError("unable to read open trades after pause")

    def cancel_fn(trade_id: int) -> None:
        # Cancelling an unfilled initial entry deletes the zero-amount trade, which can return 400/404 on readback.
        c_code, _ = _container_api_call("DELETE", f"/trades/{trade_id}/open-order", auth=auth)
        if c_code not in (200, 400, 404, 502):
            raise ValueError(f"unexpected status {c_code} cancelling open entry on trade {trade_id}")

    def reload_fn(trade_id: int) -> None:
        _container_api_call("POST", f"/trades/{trade_id}/reload", auth=auth)

    reconciliation = reconcile_pending_entries(open_trades, cancel_fn, reload_fn)
    _, cfg_after = _container_api_call("GET", "/show_config", auth=auth)
    _, trades_after = _container_api_call("GET", "/status", auth=auth)
    state_after = cfg_after.get("state") if isinstance(cfg_after, dict) else None
    if str(state_after).lower() != "paused":
        raise ValueError(f"expected paused bot state after pause, got {state_after!r}")
    remaining_entry_orders = 0
    if isinstance(trades_after, list):
        for trade in trades_after:
            for order in trade.get("orders", []):
                if order.get("is_open") and order.get("ft_order_side") == "buy":
                    remaining_entry_orders += 1
    if remaining_entry_orders:
        raise ValueError(f"{remaining_entry_orders} open buy entry orders remain after pause")
    return {
        "action": "entry_pause",
        "pause_response": msg,
        "verified_state": state_after,
        "exit_supervision_active": True,
        "reconciliation": reconciliation,
        "remaining_open_entry_orders": remaining_entry_orders,
        "paper_ledger": ledger(DB) if DB.exists() else None,
    }


def resume_entries() -> dict:
    auth = load_api_auth()
    _, show_cfg = _container_api_call("GET", "/show_config", auth=auth)
    if not isinstance(show_cfg, dict) or show_cfg.get("dry_run") is not True or show_cfg.get("trading_mode") != "spot":
        raise ValueError("refusing to resume: live API did not confirm spot dry_run=true")
    code, msg = _container_api_call("POST", "/start", auth=auth)
    if code != 200:
        raise ValueError(f"start endpoint failed with HTTP {code}: {msg}")
    _, after = _container_api_call("GET", "/show_config", auth=auth)
    state_after = after.get("state") if isinstance(after, dict) else None
    if str(state_after).lower() != "running":
        raise ValueError(f"expected running state after resume, got {state_after!r}")
    return {"action": "entry_resume", "resume_response": msg, "verified_state": state_after}


def evaluate_alerts(
    snapshot: dict,
    now: datetime | None = None,
    max_heartbeat_age: float = DEFAULT_MAX_HEARTBEAT_AGE,
    max_candle_age: float = DEFAULT_MAX_CANDLE_AGE,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    error_threshold: int = DEFAULT_ERROR_THRESHOLD,
) -> list[dict]:
    current = now or datetime.now(timezone.utc)
    alerts = []
    container_state = snapshot.get("container_state")
    logs = snapshot.get("log_health") or {}
    hb_utc = logs.get("last_heartbeat_utc")

    if container_state == "running":
        if hb_utc is None:
            started = snapshot.get("container_started")
            age = (current - parse_utc_iso(started)).total_seconds() if started else max_heartbeat_age + 1
            if age > max_heartbeat_age:
                alerts.append({
                    "code": "failed_heartbeat",
                    "detail": f"container running for {round(age, 1)}s without a logged heartbeat",
                })
        else:
            hb_age = (current - parse_utc_iso(hb_utc)).total_seconds()
            if hb_age > max_heartbeat_age:
                alerts.append({
                    "code": "failed_heartbeat",
                    "detail": f"last heartbeat is {round(hb_age, 1)}s old (limit {max_heartbeat_age}s)",
                })

    api = snapshot.get("live_api")
    if isinstance(api, dict):
        for pair, info in (api.get("candles") or {}).items():
            candle_age = info.get("completed_candle_age_seconds")
            if info.get("rows_loaded", 0) == 0 or candle_age is None:
                alerts.append({
                    "code": "stale_feed",
                    "detail": f"{pair} has no loaded candles in dataprovider",
                })
            elif candle_age > max_candle_age:
                alerts.append({
                    "code": "stale_feed",
                    "detail": f"{pair} completed candle age {round(candle_age, 1)}s exceeds {max_candle_age}s",
                })

    errors = int(logs.get("recent_error_count") or 0)
    if errors >= error_threshold:
        alerts.append({
            "code": "repeated_errors",
            "detail": f"{errors} ERROR/CRITICAL log lines in recent window (threshold {error_threshold})",
        })

    free_bytes = int(snapshot.get("free_disk_bytes") or 0)
    if free_bytes < min_free_bytes:
        alerts.append({
            "code": "disk_pressure",
            "detail": f"free disk {free_bytes} bytes is below {min_free_bytes} bytes",
        })

    restart_count = int(snapshot.get("container_restart_count") or 0)
    exit_code = snapshot.get("container_exit_code")
    launches = int(snapshot.get("launch_manifest_count") or 0)
    clean_stops = int(logs.get("clean_stops_logged") or 0)
    if restart_count > 0 or (exit_code not in (None, 0)):
        alerts.append({
            "code": "restart_detected",
            "detail": f"container restart_count={restart_count}, exit_code={exit_code}",
        })
    elif container_state == "absent" and launches > 0 and clean_stops == 0 and logs.get("startup_runs_logged", 0) > 0:
        alerts.append({
            "code": "restart_detected",
            "detail": "container is absent after startup without a clean shutdown log marker",
        })

    guard_info = snapshot.get("guard_health")
    if isinstance(guard_info, dict) and guard_info.get("policy_present"):
        latch = guard_info.get("latch")
        if latch is not None:
            alerts.append({
                "code": "guard_latched",
                "detail": f"daily entry guard latched: {latch}",
            })
        elif container_state == "running" and not guard_info.get("entries_allowed"):
            alerts.append({
                "code": "guard_stale",
                "detail": "guard lease expired or missing snapshot while container is running",
            })
        if guard_info.get("enforcement_pending"):
            alerts.append({
                "code": "guard_enforcement_pending",
                "detail": "guard latch awaits API pause or pending-entry cancellation reconciliation",
            })

    return alerts


def inspect_guard(now: datetime | None = None) -> dict:
    if not GUARD_POLICY.is_file() or GUARD_POLICY.is_symlink():
        return {"policy_present": False}
    import sys
    from datetime import timedelta
    from decimal import Decimal

    risk_dir = str(Path(__file__).resolve().parents[1] / "risk")
    if risk_dir not in sys.path:
        sys.path.insert(0, risk_dir)
    from guard import Guard

    with GUARD_POLICY.open(encoding="utf-8") as stream:
        policy = read_settings(stream)
    ratio = policy.get("max_loss_ratio")
    guard = Guard(
        path=GUARD_STATE,
        account=str(policy["account"]),
        max_loss=Decimal(str(policy["max_loss_quote"])),
        max_age=timedelta(seconds=float(policy["max_age_seconds"])),
        max_loss_ratio=Decimal(str(ratio)) if ratio is not None else None,
    )
    current = now or datetime.now(timezone.utc)
    allowed = guard.entries_allowed(current)
    state = None
    if GUARD_STATE.is_file() and not GUARD_STATE.is_symlink():
        try:
            state = json.loads(GUARD_STATE.read_text(encoding="utf-8"))
        except Exception:
            state = {"corrupt": True}
    return {
        "policy_present": True,
        "account": policy.get("account"),
        "max_loss_quote": policy.get("max_loss_quote"),
        "max_age_seconds": policy.get("max_age_seconds"),
        "entries_allowed": allowed,
        "latch": state.get("latch") if isinstance(state, dict) else "unreadable_state",
        "loss": state.get("loss") if isinstance(state, dict) else None,
        "opening_equity": state.get("opening_equity") if isinstance(state, dict) else None,
        "latest_equity": state.get("latest_equity") if isinstance(state, dict) else None,
        "last_observed_at": state.get("last_observed_at") if isinstance(state, dict) else None,
        "enforcement_pending": state.get("enforcement_pending") if isinstance(state, dict) else False,
        "last_enforcement": state.get("last_enforcement") if isinstance(state, dict) else None,
    }


def status(
    max_heartbeat_age: float = DEFAULT_MAX_HEARTBEAT_AGE,
    max_candle_age: float = DEFAULT_MAX_CANDLE_AGE,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    error_threshold: int = DEFAULT_ERROR_THRESHOLD,
) -> dict:
    process = subprocess.run([
        "docker", "inspect", "--type", "container",
        "--format", "{{json .}}", CONTAINER_NAME,
    ], capture_output=True, text=True)
    if process.returncode and "no such" not in process.stderr.lower():
        raise ValueError("unable to inspect the paper container; check Docker access")
    inspected = json.loads(process.stdout) if process.returncode == 0 else None
    state = inspected.get("State", {}) if inspected else None
    manifests = sorted(PAPER_DIR.glob("launch-*.json")) if PAPER_DIR.is_dir() else []
    log_health = inspect_logs(LOG_FILE)
    live_api = None
    if state and state.get("Status") == "running" and API_AUTH.is_file():
        try:
            live_api = probe_live_api()
        except Exception as exc:
            live_api = {"probe_error": sanitize_text(str(exc))}

    guard_health = inspect_guard()
    active_strategy = live_api.get("strategy") if isinstance(live_api, dict) else None
    guard_label = (
        "persisted_entry_halt_active_not_hard_loss_guarantee"
        if (
            active_strategy in (
                "PersonalSpotGuarded",
                "PersonalSpotBreakoutGuarded",
                "PersonalSpotMacroBreakoutGuarded",
            )
            or guard_health.get("policy_present")
        )
        else "not_integrated_no_daily_loss_enforcement_claimed"
    )
    snapshot = {
        "container_state": state["Status"] if state else "absent",
        "container_started": state.get("StartedAt") if state else None,
        "container_exit_code": state.get("ExitCode") if state and state.get("Status") != "running" else None,
        "container_restart_count": inspected.get("RestartCount", 0) if inspected else 0,
        "launch_manifest_count": len(manifests),
        "paper_ledger": ledger(DB) if DB.exists() else None,
        "order_sides": order_side_breakdown(DB) if DB.exists() else None,
        "log_health": {k: v for k, v in log_health.items() if k != "tail"},
        "guard_health": guard_health,
        "live_api": live_api,
        "free_disk_bytes": shutil.disk_usage(PAPER_DIR.parent if PAPER_DIR.exists() else Path.cwd()).free,
        "guard_enforcement": guard_label,
        "external_notifications": "disabled_requires_user_authorized_destination",
    }
    snapshot["alerts"] = evaluate_alerts(
        snapshot,
        max_heartbeat_age=max_heartbeat_age,
        max_candle_age=max_candle_age,
        min_free_bytes=min_free_bytes,
        error_threshold=error_threshold,
    )
    return snapshot


def export_sanitized_bundle(destination: Path) -> dict:
    current_status = status()
    log_info = inspect_logs(LOG_FILE)
    manifests = []
    if PAPER_DIR.is_dir():
        for item in sorted(PAPER_DIR.glob("launch-*.json"))[-5:]:
            with item.open(encoding="utf-8") as stream:
                manifests.append({"name": item.name, "manifest": read_settings(stream)})
    bundle = sanitize_value({
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": current_status,
        "recent_launches": manifests,
        "recent_log_tail": log_info.get("tail", []),
    })
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(bundle, stream, indent=2)
        stream.write("\n")
    return {"exported_to": str(destination), "alerts": bundle["status"]["alerts"]}


def pilot_digest(
    max_heartbeat_age: float = DEFAULT_MAX_HEARTBEAT_AGE,
    max_candle_age: float = DEFAULT_MAX_CANDLE_AGE,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    error_threshold: int = DEFAULT_ERROR_THRESHOLD,
) -> dict:
    current = status(
        max_heartbeat_age=max_heartbeat_age,
        max_candle_age=max_candle_age,
        min_free_bytes=min_free_bytes,
        error_threshold=error_threshold,
    )
    signals = None
    if current.get("container_state") == "running" and API_AUTH.is_file():
        try:
            signals = probe_signal_proximity()
        except Exception as exc:
            signals = {"probe_error": sanitize_text(str(exc))}
    managed = list_managed_backups(BACKUP_DIR)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "container_state": current["container_state"],
        "bot_state": (current.get("live_api") or {}).get("state"),
        "strategy": (current.get("live_api") or {}).get("strategy"),
        "paper_ledger": current["paper_ledger"],
        "guard_health": current["guard_health"],
        "alerts": current["alerts"],
        "signal_proximity": signals,
        "managed_backups": {
            "directory": str(BACKUP_DIR),
            "count": len(managed),
            "latest_snapshot": managed[0][1].name if managed else None,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "status", "digest", "signals", "verify-api", "pause", "resume",
            "backup", "snapshot-rotate", "verify-backup", "restore-drill", "export",
        ),
    )
    parser.add_argument("target_path", nargs="?", type=Path)
    parser.add_argument("isolated_dir", nargs="?", type=Path)
    parser.add_argument("--max-heartbeat-age", type=float, default=DEFAULT_MAX_HEARTBEAT_AGE)
    parser.add_argument("--max-candle-age", type=float, default=DEFAULT_MAX_CANDLE_AGE)
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--error-threshold", type=int, default=DEFAULT_ERROR_THRESHOLD)
    parser.add_argument("--keep-daily", type=int, default=DEFAULT_KEEP_DAILY_BACKUPS)
    parser.add_argument("--keep-weekly", type=int, default=DEFAULT_KEEP_WEEKLY_BACKUPS)
    args = parser.parse_args()

    requires_target = {"backup", "verify-backup", "restore-drill", "export"}
    optional_target = {"snapshot-rotate"}
    if args.action in requires_target and args.target_path is None:
        parser.error(f"{args.action} requires a path argument")
    if args.action not in (requires_target | optional_target) and args.target_path is not None:
        parser.error(f"{args.action} takes no path argument")
    if (args.action == "restore-drill") != (args.isolated_dir is not None):
        parser.error("restore-drill requires both <backup_path> and <isolated_dir>")

    try:
        check_paper_paths(BASELINE)
        if args.action == "status":
            print(json.dumps(status(
                max_heartbeat_age=args.max_heartbeat_age,
                max_candle_age=args.max_candle_age,
                min_free_bytes=args.min_free_bytes,
                error_threshold=args.error_threshold,
            ), indent=2))
        elif args.action == "digest":
            print(json.dumps(pilot_digest(
                max_heartbeat_age=args.max_heartbeat_age,
                max_candle_age=args.max_candle_age,
                min_free_bytes=args.min_free_bytes,
                error_threshold=args.error_threshold,
            ), indent=2))
        elif args.action == "signals":
            print(json.dumps(probe_signal_proximity(), indent=2))
        elif args.action == "verify-api":
            print(json.dumps(probe_live_api(), indent=2))
        elif args.action == "pause":
            print(json.dumps(pause_entries(), indent=2))
        elif args.action == "resume":
            print(json.dumps(resume_entries(), indent=2))
        elif args.action == "backup":
            backup(args.target_path)
            print(f"Paper SQLite backup created at {args.target_path}")
        elif args.action == "snapshot-rotate":
            print(json.dumps(snapshot_and_rotate_backups(
                backup_dir=args.target_path or BACKUP_DIR,
                keep_daily=args.keep_daily,
                keep_weekly=args.keep_weekly,
            ), indent=2))
        elif args.action == "verify-backup":
            with closing(connect_readonly(args.target_path)) as copy:
                if copy.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise ValueError("backup failed SQLite quick_check")
            print(json.dumps(ledger(args.target_path), indent=2))
        elif args.action == "restore-drill":
            print(json.dumps(restore_drill(args.target_path, args.isolated_dir), indent=2))
        elif args.action == "export":
            print(json.dumps(export_sanitized_bundle(args.target_path), indent=2))
    except (OSError, ValueError, sqlite3.Error, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"Paper operations check failed: {exc}\n")


if __name__ == "__main__":
    main()
