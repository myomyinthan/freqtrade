import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "risk")]

import paper_status
from guard import Guard, Snapshot, paper_equity


class BackupTest(TestCase):
    def test_online_backup_preserves_paper_trades_and_pending_orders(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "paper.sqlite"
            snapshot = Path(folder) / "backup.sqlite"
            with closing(sqlite3.connect(source)) as db:
                db.executescript(
                    "PRAGMA journal_mode=WAL; CREATE TABLE trades(is_open INTEGER); "
                    "CREATE TABLE orders(ft_is_open INTEGER); "
                    "INSERT INTO trades VALUES (1), (0), (0); INSERT INTO orders VALUES(1);"
                )
                with patch.object(paper_status, "DB", source):
                    paper_status.backup(snapshot)
                    with self.assertRaises(FileExistsError):
                        paper_status.backup(snapshot)
            self.assertEqual(paper_status.ledger(snapshot), {
                "open_positions": 1, "closed_positions": 2, "pending_orders": 1,
            })

    def test_isolated_restore_leaves_production_db_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "baseline.paper.sqlite"
            snapshot = root / "backup.sqlite"
            isolated = root / "isolated-restore"
            with closing(sqlite3.connect(source)) as db:
                db.executescript(
                    "CREATE TABLE trades(is_open INTEGER); "
                    "CREATE TABLE orders(ft_is_open INTEGER, ft_order_side TEXT); "
                    "INSERT INTO trades VALUES (1), (0); "
                    "INSERT INTO orders VALUES (1, 'sell'), (0, 'buy');"
                )
            with patch.object(paper_status, "DB", source):
                paper_status.backup(snapshot)
                before = paper_status.sha256_file(source)
                result = paper_status.restore_drill(snapshot, isolated, source_db=source)
                after = paper_status.sha256_file(source)
            self.assertEqual(before, after)
            self.assertTrue(result["production_db_unchanged"])
            self.assertEqual(result["ledger"], {
                "open_positions": 1, "closed_positions": 1, "pending_orders": 1,
            })
            self.assertEqual(result["order_sides"], {
                "pending_entry_orders": 0, "pending_exit_orders": 1,
            })


class PaperMonitoringAndOpsTest(TestCase):
    def test_parse_utc_iso_accepts_docker_nanosecond_timestamps(self):
        parsed = paper_status.parse_utc_iso("2026-11-16T10:49:40.705157351Z")
        self.assertEqual(parsed, datetime(2026, 11, 16, 10, 49, 40, 705157, tzinfo=timezone.utc))
        self.assertEqual(
            paper_status.parse_utc_iso("2026-11-16T10:49:40+00:00"),
            datetime(2026, 11, 16, 10, 49, 40, tzinfo=timezone.utc),
        )

    def test_alerts_detect_stale_feed_heartbeat_errors_disk_and_restart(self):
        now = datetime(2026, 11, 16, 9, 0, 0, tzinfo=timezone.utc)
        snapshot = {
            "container_state": "running",
            "container_started": "2026-11-16T08:00:00Z",
            "container_exit_code": None,
            "container_restart_count": 1,
            "launch_manifest_count": 1,
            "free_disk_bytes": 1024,
            "log_health": {
                "last_heartbeat_utc": "2026-11-16T08:50:00+00:00",
                "recent_error_count": 4,
                "startup_runs_logged": 1,
                "clean_stops_logged": 0,
            },
            "live_api": {
                "candles": {
                    "BTC/USDT": {
                        "rows_loaded": 150,
                        "completed_candle_age_seconds": 9000.0,
                    },
                },
            },
        }
        codes = {item["code"] for item in paper_status.evaluate_alerts(snapshot, now=now)}
        self.assertEqual(codes, {
            "failed_heartbeat", "stale_feed", "repeated_errors",
            "disk_pressure", "restart_detected",
        })

    def test_reconcile_pending_entries_cancels_buys_and_preserves_protective_sells(self):
        cancelled, reloaded = [], []
        trades = [
            {
                "trade_id": 11, "pair": "BTC/USDT", "has_open_orders": True,
                "orders": [{"is_open": True, "ft_order_side": "buy"}],
            },
            {
                "trade_id": 12, "pair": "ETH/USDT", "has_open_orders": True,
                "orders": [{"is_open": True, "ft_order_side": "sell"}],
            },
        ]
        out = paper_status.reconcile_pending_entries(
            trades, cancelled.append, reloaded.append,
        )
        self.assertEqual(cancelled, [11])
        self.assertEqual(reloaded, [11])
        self.assertEqual(out["cancelled_entry_trade_ids"], [11])
        self.assertEqual(len(out["preserved_exit_trades"]), 1)
        self.assertEqual(out["preserved_exit_trades"][0]["trade_id"], 12)

    def test_sanitize_redacts_secrets_and_auth_headers(self):
        raw = {
            "password": "super-secret-value",
            "jwt_secret_key": "0123456789abcdef",
            "log": "Authorization: Basic dXNlcjpwYXNz token=abc123xyz",
        }
        cleaned = paper_status.sanitize_value(raw)
        self.assertEqual(cleaned["password"], "[REDACTED]")
        self.assertEqual(cleaned["jwt_secret_key"], "[REDACTED]")
        self.assertNotIn("dXNlcjpwYXNz", cleaned["log"])
        self.assertNotIn("abc123xyz", cleaned["log"])

    def test_signal_proximity_summary_reports_macro_regime_and_breakout_distances(self):
        bear_row = {
            "date": "2026-11-16T18:00:00Z",
            "close": 65000.0,
            "volume": 8.0,
            "warmed_up": True,
            "sma120": 68250.0,
            "sma360": 73125.0,
            "sma360_slope24": -800.0,
            "prior_high_336": 81250.0,
            "prior_low_96": 62500.0,
            "prior_vol_sma24": 12.0,
            "enter_long": 0,
            "exit_long": 0,
        }
        bear = paper_status.summarize_pair_signal_row(
            "BTC/USDT", "PersonalSpotMacroBreakoutGuarded", bear_row,
        )
        self.assertEqual(bear["regime"], "bear_or_neutral_cash")
        self.assertEqual(bear["entry_gates_passed"], "1/6")
        self.assertEqual(bear["proximity_pct"]["move_to_sma120_pct"], 5.0)
        self.assertEqual(bear["proximity_pct"]["move_to_14d_breakout_pct"], 25.0)
        self.assertEqual(bear["proximity_pct"]["cushion_above_4d_exit_pct"], 4.0)

        bull_row = {
            **bear_row,
            "close": 82000.0,
            "volume": 20.0,
            "sma120": 76000.0,
            "sma360": 72000.0,
            "sma360_slope24": 450.0,
            "enter_long": 1,
        }
        bull = paper_status.summarize_pair_signal_row(
            "BTC/USDT", "PersonalSpotMacroBreakoutGuarded", bull_row,
        )
        self.assertEqual(bull["regime"], "bull_macro_aligned")
        self.assertEqual(bull["entry_gates_passed"], "6/6")
        self.assertEqual(bull["enter_long"], 1)

    def test_managed_backup_rotation_keeps_daily_and_weekly_and_ignores_manual_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "baseline.paper.sqlite"
            backup_dir = root / "backups"
            with closing(sqlite3.connect(source)) as db:
                db.executescript(
                    "CREATE TABLE trades(is_open INTEGER); "
                    "CREATE TABLE orders(ft_is_open INTEGER, ft_order_side TEXT); "
                    "INSERT INTO trades VALUES (0); INSERT INTO orders VALUES (0, 'buy');"
                )
            backup_dir.mkdir(mode=0o700)
            manual_file = backup_dir / "morning-manual.backup.sqlite"
            manual_file.write_text("keep-manual", encoding="utf-8")

            base_day = datetime(2026, 11, 1, 8, 0, 0, tzinfo=timezone.utc)
            # Create 10 daily snapshots across 10 consecutive days with keep_daily=3, keep_weekly=2.
            for day_offset in range(10):
                ts = base_day + timedelta(days=day_offset)
                out = paper_status.snapshot_and_rotate_backups(
                    backup_dir=backup_dir,
                    keep_daily=3,
                    keep_weekly=2,
                    source_db=source,
                    now=ts,
                )
            kept = out["retention"]["kept"]
            # Must keep the 3 most recent days (Nov 10, Nov 9, Nov 8) plus newest from prior ISO week (Nov 8 is W45, Nov 1 is W44).
            self.assertGreaterEqual(len(kept), 3)
            self.assertLessEqual(len(kept), 4)
            self.assertIn("paper-20261110T080000Z.sqlite", kept)
            self.assertTrue(manual_file.is_file())
            # Companion metadata files for pruned snapshots must also be removed.
            meta_files = {p.name for p in backup_dir.glob("*.meta.json")}
            self.assertEqual(
                meta_files,
                {name.replace(".sqlite", ".meta.json") for name in kept},
            )


class PaperGuardTest(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "guard.json"
        self.max_age = timedelta(seconds=30)
        self.midnight = datetime(2024, 1, 1, tzinfo=timezone.utc)
        self.guard = self.make_guard()

    def make_guard(self):
        return Guard(self.path, "paper-fixture", Decimal("20"), self.max_age)

    def observe(self, seconds, equity, flows="0", pending=(), reconciled=True):
        time = self.midnight + timedelta(seconds=seconds)
        return self.guard.observe(
            Snapshot("paper-fixture", time, Decimal(equity), Decimal(flows), reconciled, pending), time,
        )

    def test_equity_marks_holdings_and_uses_net_external_flows(self):
        self.assertFalse(self.guard.entries_allowed(self.midnight))
        self.assertEqual(paper_equity(
            Decimal("900"), [(Decimal("2"), Decimal("51"))], Decimal("2"),
        ), Decimal("1000"))
        self.observe(0, "1000")
        self.assertIsNone(self.observe(10, "1100", "100")["latch"])
        self.assertEqual(self.observe(20, "1080", "100", ("pending",))["latch"], "daily_loss")
        self.assertFalse(self.make_guard().entries_allowed(self.midnight + timedelta(seconds=20)))
        self.observe(25, "1100", "100", ("pending",))
        with self.assertRaisesRegex(ValueError, "no pending"):
            self.guard.rearm(self.midnight + timedelta(seconds=25), "checked")
        self.observe(29, "1100", "100")
        self.guard.rearm(self.midnight + timedelta(seconds=29), "reconciled")
        self.assertTrue(self.guard.entries_allowed(self.midnight + timedelta(seconds=29)))

    def test_stale_and_missing_midnight_denies_after_restart(self):
        state = self.observe(10, "1000")
        self.assertEqual(state["latch"], "missing_utc_opening_equity")
        state = self.observe(24 * 3600, "1000")
        self.assertEqual(state["latch"], "missing_utc_opening_equity")
        self.guard.rearm(self.midnight + timedelta(days=1), "restored opening snapshot")
        self.assertFalse(self.guard.entries_allowed(self.midnight + timedelta(days=1, seconds=31)))
        self.assertEqual(self.observe(24 * 3600 + 40, "1000")["latch"], "heartbeat_gap")
        self.path.write_text("{invalid", encoding="utf-8")
        self.assertFalse(self.guard.entries_allowed(self.midnight + timedelta(days=1, seconds=40)))
