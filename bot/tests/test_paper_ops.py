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
