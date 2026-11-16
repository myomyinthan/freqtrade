"""Host readiness stays a dry-run decision and does not invent a machine."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import TestCase

BOT_DIR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BOT_DIR / "scripts")]

import host_ready


def lock() -> dict:
    with (BOT_DIR / "VERSION.lock.json").open(encoding="utf-8") as stream:
        return json.load(stream)


class HostReadyTest(TestCase):
    def test_this_laptop_is_not_an_always_on_host(self):
        report = host_ready.assess_host(lock(), system="Darwin", machine="arm64")
        self.assertEqual(report["verdict"], "not_an_always_on_host")
        self.assertFalse(report["install_performed"])
        self.assertFalse(report["paid_host_created"])
        self.assertIn("sha256:956c03780934", report["recorded_linux_amd64_image"])
        self.assertEqual(report["active_compose_platform"], "linux/arm64")

    def test_matching_linux_arm64_is_ready_without_installing(self):
        report = host_ready.assess_host(lock(), system="Linux", machine="aarch64")
        self.assertEqual(report["verdict"], "ready_for_dry_run_systemd_install")
        self.assertFalse(report["install_performed"])

    def test_linux_amd64_must_repoint_compose_before_install(self):
        report = host_ready.assess_host(lock(), system="Linux", machine="x86_64")
        self.assertEqual(report["verdict"], "repoint_compose_to_recorded_amd64_digest_before_install")
        self.assertIn("sha256:956c03780934", report["recorded_linux_amd64_image"])
        self.assertNotEqual(report["recorded_linux_amd64_image"], report["active_compose_image"])

    def test_live_settings_fail_without_echoing_the_secret(self):
        secret = "super-secret-value"
        report = host_ready.assess_host(
            lock(),
            system="Linux",
            machine="x86_64",
            settings={
                "dry_run": False,
                "trading_mode": "futures",
                "force_entry_enable": True,
                "exchange": {"key": secret, "secret": secret},
            },
        )
        self.assertEqual(report["verdict"], "dry_run_contract_failed")
        self.assertEqual(report["problems"], [
            "dry_run_false",
            "trading_mode_not_spot",
            "force_entry_enabled",
            "exchange_credential_present",
        ])
        blob = json.dumps(report)
        self.assertNotIn(secret, blob)
