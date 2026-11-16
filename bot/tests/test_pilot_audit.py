"""Unit tests for B17 pilot continuity/fill-drift audits and B20 systemd unit safety."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase

BOT_DIR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BOT_DIR / "scripts")]

import pilot_audit


class PilotAuditTest(TestCase):
    def test_uptime_continuity_detects_macbook_sleep_gap(self):
        lines = [
            "2026-11-16 10:49:50,040 - freqtrade.worker - INFO - Bot heartbeat. PID=7, version='2026.10', state='RUNNING'",
            "2026-11-16 10:50:50,100 - freqtrade.worker - INFO - Bot heartbeat. PID=7, version='2026.10', state='RUNNING'",
            # 45-minute laptop sleep gap
            "2026-11-16 11:35:50,200 - freqtrade.worker - INFO - Bot heartbeat. PID=7, version='2026.10', state='RUNNING'",
        ]
        result = pilot_audit.audit_uptime_continuity(
            lines,
            since_utc=datetime(2026, 11, 16, 10, 49, 40, tzinfo=timezone.utc),
            now_utc=datetime(2026, 11, 16, 11, 36, 0, tzinfo=timezone.utc),
            max_gap_seconds=180.0,
        )
        self.assertFalse(result["continuous_claim_valid"])
        self.assertEqual(len(result["uptime_gaps"]), 1)
        self.assertGreater(result["uptime_gaps"][0]["gap_seconds"], 2600)

    def test_uptime_continuity_passes_without_gaps(self):
        start = datetime(2026, 11, 16, 10, 0, 0, tzinfo=timezone.utc)
        lines = [
            f"{(start + timedelta(seconds=60 * i)).strftime('%Y-%m-%d %H:%M:%S')},000"
            f" - freqtrade.worker - INFO - Bot heartbeat. PID=7, version='2026.10', state='RUNNING'"
            for i in range(1, 6)
        ]
        result = pilot_audit.audit_uptime_continuity(
            lines,
            since_utc=start,
            now_utc=start + timedelta(minutes=5),
            max_gap_seconds=180.0,
        )
        self.assertTrue(result["continuous_claim_valid"])
        self.assertEqual(result["uptime_gaps"], [])
        self.assertEqual(result["heartbeat_count"], 5)

    def test_paper_vs_model_measures_adverse_fill_and_fee_drift(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "baseline.paper.sqlite"
            with closing(sqlite3.connect(db)) as conn:
                conn.executescript(
                    "CREATE TABLE trades ("
                    "id INTEGER PRIMARY KEY, pair TEXT, is_open INTEGER, "
                    "fee_open REAL, fee_close REAL, open_rate REAL, open_rate_requested REAL, "
                    "close_rate REAL, close_rate_requested REAL, close_profit_abs REAL, "
                    "stake_amount REAL, amount REAL, open_date TEXT, close_date TEXT, "
                    "stop_loss REAL, exit_reason TEXT, strategy TEXT, enter_tag TEXT);"
                    "CREATE TABLE orders ("
                    "ft_trade_id INTEGER, ft_order_side TEXT, status TEXT, ft_cancel_reason TEXT);"
                    "INSERT INTO trades VALUES ("
                    "1, 'BTC/USDT', 0, 0.001, 0.001, 101.0, 100.0, 109.0, 110.0, 4.0, "
                    "50.0, 0.5, '2026-11-16 12:00:00.000000', '2026-11-16 18:00:00.000000', "
                    "NULL, 'macro_channel_exit', 'PersonalSpotMacroBreakoutGuarded', "
                    "'macro_donchian_up');"
                    "INSERT INTO orders VALUES (1, 'buy', 'closed', NULL);"
                    "INSERT INTO orders VALUES (1, 'sell', 'closed', NULL);"
                )
            candle_opens = {
                "BTC/USDT": {
                    "2026-11-16T12:00:00+00:00": 100.0,
                    "2026-11-16T18:00:00+00:00": 110.0,
                },
            }
            result = pilot_audit.audit_paper_vs_model(
                db,
                model_fee_per_side=0.001,
                strategy_filter="PersonalSpotMacroBreakoutGuarded",
                candle_opens=candle_opens,
            )
            self.assertEqual(result["natural_closed_trades"], 1)
            self.assertEqual(result["open_trades"], 0)
            self.assertEqual(
                result["execution_drift_bps"]["entry_vs_requested_rate"]["mean_adverse_bps"],
                100.0,
            )
            self.assertAlmostEqual(
                result["execution_drift_bps"]["exit_vs_requested_rate"]["mean_adverse_bps"],
                (1.0 - 109.0 / 110.0) * 10_000.0,
                places=3,
            )
            self.assertEqual(
                result["execution_drift_bps"]["entry_vs_1h_candle_open"]["mean_adverse_bps"],
                100.0,
            )
            self.assertAlmostEqual(
                result["execution_drift_bps"]["exit_vs_modeled_boundary_or_stop"]["mean_adverse_bps"],
                (1.0 - 109.0 / 110.0) * 10_000.0,
                places=3,
            )
            self.assertEqual(
                result["fee_comparison"]["observed_fee_drift_bps"]["mean_adverse_bps"],
                0.0,
            )

    def test_b17_gate_tracks_progress_and_blocks_on_gaps_or_force_entries(self):
        continuous = {
            "observed_span_days": 12.5,
            "continuous_claim_valid": True,
        }
        execution = {
            "natural_closed_trades": 8,
            "force_entry_trades": 0,
        }
        progress = pilot_audit.evaluate_b17_gate(
            continuity=continuous,
            execution=execution,
            active_alerts=[],
            target_days=30.0,
            target_trades=30,
        )
        self.assertEqual(progress["verdict"], "observing_in_progress")
        self.assertEqual(progress["remaining_days"], 17.5)
        self.assertEqual(progress["remaining_natural_trades"], 22)

        met = continuous | {"observed_span_days": 31.0}
        met_exec = execution | {"natural_closed_trades": 30}
        ready = pilot_audit.evaluate_b17_gate(
            continuity=met,
            execution=met_exec,
            active_alerts=[],
            target_days=30.0,
            target_trades=30,
        )
        self.assertEqual(ready["verdict"], "b17_minimum_observation_met_ready_for_b21_dossier")

        gapped = continuous | {"continuous_claim_valid": False}
        blocked = pilot_audit.evaluate_b17_gate(
            continuity=gapped,
            execution=execution | {"force_entry_trades": 1},
            active_alerts=[{"code": "failed_heartbeat"}],
            target_days=30.0,
            target_trades=30,
        )
        self.assertEqual(blocked["verdict"], "continuity_or_safety_exception_review_required")
        self.assertIn("uptime_gap_or_stop_detected_in_observation_window", blocked["anomalies"])
        self.assertIn("force_entry_detected_invalidates_natural_trade_sample", blocked["anomalies"])
        self.assertIn("active_operational_alerts_present", blocked["anomalies"])


class SystemdBundleSafetyTest(TestCase):
    def setUp(self):
        self.root = BOT_DIR / "deploy" / "systemd"

    def _read(self, name: str) -> str:
        return (self.root / name).read_text(encoding="utf-8")

    def test_units_are_dry_run_only_with_hardening_and_no_host_ports(self):
        for name in (
            "personalspot-guard.service",
            "personalspot-paper.service",
            "personalspot-backup.service",
            "personalspot-backup.timer",
            "README.md",
        ):
            self.assertTrue((self.root / name).is_file(), name)

        paper = self._read("personalspot-paper.service")
        guard = self._read("personalspot-guard.service")
        backup = self._read("personalspot-backup.service")
        timer = self._read("personalspot-backup.timer")
        readme = self._read("README.md")

        self.assertIn("PersonalSpotMacroBreakoutGuarded", paper)
        self.assertIn("--local-api", paper)
        self.assertIn("NoNewPrivileges=yes", paper)
        self.assertIn("Requires=personalspot-guard.service", paper)
        self.assertNotIn("ports=", paper)
        self.assertNotIn("FREQTRADE__", paper)

        self.assertIn("guard_runner.py watch", guard)
        self.assertIn("NoNewPrivileges=yes", guard)
        self.assertIn("ProtectSystem=strict", guard)
        self.assertIn("ReadWritePaths=%h/freqtrade/bot/runtime/paper", guard)

        self.assertIn("snapshot-rotate", backup)
        self.assertIn("pilot_audit.py", backup)
        self.assertIn("UMask=0077", backup)

        self.assertIn("00:15:00 UTC", timer)
        self.assertIn("credential-free", readme.lower())
        self.assertIn("zero host ports", readme.lower())
        self.assertIn("linux/amd64", readme)
