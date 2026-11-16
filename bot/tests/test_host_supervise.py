"""Safety tests for macOS launchd supervision of the dry-run paper pilot."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase

BOT_DIR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BOT_DIR / "scripts")]

import host_supervise


class HostSuperviseDecisionTest(TestCase):
    def test_adopts_existing_guard_and_paper_without_a_second_writer(self):
        commands = [
            "/usr/bin/python3 bot/scripts/guard_runner.py watch bot/configs/pilot.local.json",
            "/usr/bin/python3 bot/scripts/preflight.py run bot/configs/pilot.local.json "
            "--strategy PersonalSpotMacroBreakoutGuarded --local-api",
            "python /freqtrade/bot/scripts/preflight.py --inside run --strategy "
            "PersonalSpotMacroBreakoutGuarded --state running --local-api",
        ]
        self.assertFalse(host_supervise.service_should_start("guard", commands, True))
        self.assertFalse(host_supervise.service_should_start("paper", commands, True))
        self.assertFalse(host_supervise.service_should_start("paper", [], True))
        self.assertTrue(host_supervise.service_should_start("guard", [], False))
        self.assertTrue(host_supervise.service_should_start("paper", [], False))

    def test_utc_daily_slot_runs_once_after_0015(self):
        before = datetime(2026, 11, 16, 0, 14, 59, tzinfo=timezone.utc)
        due = datetime(2026, 11, 16, 0, 15, 0, tzinfo=timezone.utc)
        later = datetime(2026, 11, 16, 21, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(host_supervise.utc_daily_due(before, None))
        self.assertTrue(host_supervise.utc_daily_due(due, None))
        self.assertTrue(host_supervise.utc_daily_due(later, None))
        self.assertFalse(host_supervise.utc_daily_due(later, "2026-11-16"))
        self.assertTrue(host_supervise.utc_daily_due(later, "2026-11-15"))

    def test_launchd_plists_are_credential_free_and_dry_run_only(self):
        log_dir = Path("/tmp/personalspot-host")
        for role in ("guard", "paper", "daily"):
            plist = host_supervise.agent_plist(
                role,
                python="/usr/bin/python3",
                path_env="/usr/local/bin:/usr/bin:/bin",
                log_dir=log_dir,
            )
            blob = " ".join(str(part) for part in plist["ProgramArguments"])
            self.assertEqual(plist["Label"], host_supervise.LABELS[role])
            self.assertNotIn("FREQTRADE__", blob)
            self.assertNotIn("api_key", blob.lower())
            self.assertNotIn("password", blob.lower())
            self.assertNotIn("ports=", blob)
            self.assertEqual(plist["LimitLoadToSessionType"], "Aqua")
        paper = host_supervise._role_argv("paper")
        self.assertIn("PersonalSpotMacroBreakoutGuarded", paper)
        self.assertIn("--local-api", paper)
        self.assertNotIn("--dry-run", paper)
        guard = host_supervise._role_argv("guard")
        self.assertTrue(any(part.endswith("guard_runner.py") for part in guard))
        self.assertIn("watch", guard)
        daily = host_supervise.agent_plist(
            "daily",
            python="/usr/bin/python3",
            path_env="/usr/bin:/bin",
            log_dir=log_dir,
        )
        self.assertEqual(daily["StartInterval"], 900)
        self.assertNotIn("KeepAlive", daily)
        self.assertTrue(host_supervise.launchd_blocked(
            "can't open file '/Users/me/Documents/repo/host_supervise.py': [Errno 1] Operation not permitted"
        ))
        self.assertFalse(host_supervise.launchd_blocked(""))
        self.assertTrue(host_supervise.agent_plist(
            "guard",
            python="/usr/bin/python3",
            path_env="/usr/bin:/bin",
            log_dir=log_dir,
        )["KeepAlive"])
