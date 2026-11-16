import io
import json
import math
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import TestCase, skipIf
from unittest.mock import patch

BOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOT_DIR / "scripts"))

try:
    if sys.version_info < (3, 12):
        raise ImportError("Freqtrade requires Python 3.12")
    import pandas as pd
    from freqtrade.main import main as freqtrade_main
    from freqtrade.resolvers import ExchangeResolver
except ImportError:
    pd = None

from preflight import resolve_config
from report_results import load_stats, summarize


@skipIf(pd is None, "run in the pinned Freqtrade container")
class SyntheticEngineTest(TestCase):
    def test_backtest_export_and_diagnostics_without_exchange_io(self):
        original_load = ExchangeResolver.load_exchange

        def offline_exchange(config, **kwargs):
            adapter = original_load(config, validate=False)
            adapter._markets = {
                "BTC/USD": {
                    "symbol": "BTC/USD", "id": "BTCUSD", "base": "BTC", "quote": "USD",
                    "active": True, "spot": True, "type": "spot",
                    "precision": {"price": 0.01, "amount": 0.000001},
                    "limits": {"amount": {"min": 0.0001, "max": None}, "cost": {"min": 1, "max": None}},
                },
            }
            return adapter

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dates = pd.date_range("2024-01-01", periods=35 * 24, tz="UTC", freq="1h")
            close = [100 + 5 * math.sin(i * math.tau / 38) for i in range(len(dates))]
            opening = [close[0], *close[:-1]]
            pd.DataFrame({
                "date": dates, "open": opening,
                "high": [max(a, b) + 0.2 for a, b in zip(opening, close)],
                "low": [min(a, b) - 0.2 for a, b in zip(opening, close)],
                "close": close, "volume": 1.0,
            }).to_feather(root / "BTC_USD-1h.feather")
            config = resolve_config({
                "exchange": {"name": "kraken", "pair_whitelist": ["BTC/USD"]},
                "stake_currency": "USD", "dry_run_wallet": 1000, "stake_amount": 50,
            })
            config.pop("db_url")
            config.update(dataformat_ohlcv="feather", fee=0.002)
            settings = root / "settings.json"
            settings.write_text(json.dumps(config), encoding="utf-8")
            common = [
                "-c", str(settings), "--userdir", directory, "--strategy-path",
                str(BOT_DIR / "strategies"), "--strategy", "PersonalSpotBaseline",
                "--datadir", directory, "--timerange", "20240119-20240203T2359",
            ]
            checks = {
                "backtesting": [
                    "--enable-protections", "--cache", "none", "--export", "trades",
                    "--backtest-directory", directory, "--fee", "0.002",
                ],
                "lookahead-analysis": [
                    "--minimum-trade-amount", "3", "--targeted-trade-amount", "5",
                    "--lookahead-analysis-exportfilename", str(root / "lookahead.csv"),
                ],
                "recursive-analysis": ["-p", "BTC/USD", "--startup-candle", "50", "100", "200", "400"],
            }
            with patch.object(ExchangeResolver, "load_exchange", side_effect=offline_exchange):
                for command, flags in checks.items():
                    captured = io.StringIO()
                    with redirect_stdout(captured), redirect_stderr(captured):
                        with self.assertRaises(SystemExit) as result:
                            freqtrade_main([command, *common, *flags])
                    self.assertIn(result.exception.code, (0, None), captured.getvalue())
                    self.assertNotIn("Configuration error:", captured.getvalue())
                    if command == "recursive-analysis":
                        self.assertIn("Start checking for recursive bias", captured.getvalue())
            report = summarize(load_stats(next(root.glob("backtest-result-*.zip"))))
            self.assertGreater(report["trade_count"], 0)
            self.assertGreater(report["exit_reasons"]["stop_loss"], 0)
            self.assertIn("PersonalSpotBaseline,False", (root / "lookahead.csv").read_text())
