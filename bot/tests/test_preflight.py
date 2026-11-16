import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import preflight


class PaperPreflightTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.settings_file = self.root / "paper.json"
        self.paper_dir = self.root / "runtime" / "paper"
        self.settings = {
            "exchange": {"name": "kraken", "pair_whitelist": ["BTC/USD"]},
            "stake_currency": "USD",
            "stake_amount": 50,
            "dry_run_wallet": 1000,
        }

    def invoke(self, mode="run", environment=None):
        self.settings_file.write_text(json.dumps(self.settings), encoding="utf-8")
        with (
            patch.dict(os.environ, environment or {}, clear=True),
            patch.object(preflight, "PAPER_DIR", self.paper_dir),
            patch.object(sys, "argv", ["preflight.py", mode, str(self.settings_file)]),
            patch.object(preflight, "run_container", return_value=0) as launcher,
            redirect_stderr(io.StringIO()),
            redirect_stdout(io.StringIO()),
        ):
            code = preflight.main()
        return code, launcher

    def test_valid_settings_resolve_to_spot_paper_with_dedicated_db(self):
        code, launcher = self.invoke()
        self.assertEqual(code, 0)
        launcher.assert_called_once()
        config = launcher.call_args.args[2]
        self.assertIs(config["dry_run"], True)
        self.assertEqual(config["trading_mode"], "spot")
        self.assertIs(config["force_entry_enable"], False)
        self.assertEqual(config["db_url"], preflight.DB_URL)
        self.assertEqual(config["exchange"]["pair_whitelist"], ["BTC/USD"])

    def test_dry_run_environment_override_cannot_launch(self):
        code, launcher = self.invoke(environment={"FREQTRADE__DRY_RUN": "false"})
        self.assertEqual(code, 2)
        launcher.assert_not_called()
        self.assertFalse(self.paper_dir.exists())

    def test_config_overrides_cannot_change_mode_force_entry_or_db(self):
        for override in (
            {"dry_run": False}, {"trading_mode": "futures"}, {"force_entry_enable": True},
            {"db_url": "sqlite:///tradesv3.sqlite"}, {"add_config_files": ["other.json"]},
        ):
            with self.subTest(override=override), patch.dict(self.settings, override):
                code, launcher = self.invoke()
                self.assertEqual(code, 2)
                launcher.assert_not_called()

    def test_missing_market_inputs_and_invalid_stake_cannot_launch(self):
        for override in (
            {"exchange": {"name": None, "pair_whitelist": []}},
            {"stake_currency": None}, {"stake_amount": True}, {"stake_amount": 501},
            {"exchange": {"name": "kraken", "pair_whitelist": ["BTC/USD:USD"]}},
            {"exchange": {"name": "kraken", "pair_whitelist": ["BTC/USD"], "secret": "fixture"}},
        ):
            with self.subTest(override=override), patch.dict(self.settings, override):
                code, launcher = self.invoke()
                self.assertEqual(code, 2)
                launcher.assert_not_called()

    def test_symlink_and_hardlink_to_live_database_cannot_launch(self):
        self.paper_dir.mkdir(parents=True)
        live_db = self.root / "live.sqlite"
        live_db.touch()
        paper_db = self.paper_dir / preflight.DB_NAME
        for make_link in (lambda: paper_db.symlink_to(live_db), lambda: os.link(live_db, paper_db)):
            make_link()
            code, launcher = self.invoke()
            self.assertEqual(code, 2)
            launcher.assert_not_called()
            paper_db.unlink()

    def test_check_never_starts_compose_or_creates_runtime_directory(self):
        code, launcher = self.invoke(mode="check")
        self.assertEqual(code, 0)
        launcher.assert_not_called()
        self.assertFalse(self.paper_dir.exists())

    def test_engine_receives_validated_config_on_stdin(self):
        stub = self.root / "freqtrade"
        stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >&2\n/bin/cat\n', encoding="utf-8")
        stub.chmod(0o700)
        process = subprocess.run(
            [sys.executable, str(preflight.BOT_DIR / "scripts" / "preflight.py"), "--inside", "run"],
            input=json.dumps(self.settings), capture_output=True, text=True,
            env={"PATH": str(self.root)}, check=True,
        )
        self.assertEqual(process.stderr.splitlines()[:3], ["trade", "-c", "-"])
        self.assertEqual(process.stderr.splitlines()[-2:], ["--strategy", "PaperScaffold"])
        self.assertEqual(json.loads(process.stdout), preflight.resolve_config(self.settings))


if __name__ == "__main__":
    unittest.main()
