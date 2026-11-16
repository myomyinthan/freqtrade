import sys
import tempfile
from importlib.util import find_spec
from pathlib import Path
from unittest import TestCase, skipIf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from report_results import summarize

try:
    import pandas as pd
    from check_data import audit_file
except ImportError:
    pd = None


@skipIf(pd is None or find_spec("pyarrow") is None, "run in the pinned Freqtrade container")
class DataAuditTest(TestCase):
    def test_audit_detects_missing_and_duplicate_candles(self):
        start = pd.Timestamp("2024-01-01", tz="UTC")
        end = start + pd.Timedelta(hours=4)
        frame = pd.DataFrame({
            "date": pd.date_range(start, end, freq="1h", inclusive="left"),
            "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "volume": 1.0,
        })
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "BTC_USD-1h.feather"
            frame.to_feather(file)
            self.assertEqual(audit_file(file, start, end, 60)["requested_rows"], 4)
            frame.drop(index=1).reset_index(drop=True).to_feather(file)
            with self.assertRaisesRegex(ValueError, "missing candles"):
                audit_file(file, start, end, 60)
            frame.loc[1, "date"] = start
            frame.to_feather(file)
            with self.assertRaisesRegex(ValueError, "duplicated"):
                audit_file(file, start, end, 60)


class ResearchReportTest(TestCase):
    def test_fill_stress_and_undefined_metrics(self):
        base = {"starting_balance": 1000, "trades": []}
        self.assertIsNone(summarize(base)["profit_factor"])
        trade = {
            "pair": "BTC/USD", "open_rate": 100, "close_rate": 110,
            "fee_open": 0.01, "fee_close": 0.01, "amount": 1, "profit_abs": 7.9,
            "open_timestamp": 1704067200000, "close_timestamp": 1704070800000,
            "close_date": "2024-01-01T01:00:00+00:00", "exit_reason": "exit_signal",
        }
        report = summarize({**base, "trades": [trade]})
        self.assertAlmostEqual(report["estimated_quote_fees"], 2.1)
        self.assertAlmostEqual(report["fill_cost_net_returns"]["50"], (7.9 - 1.0495) / 1000)
        self.assertEqual(report["hours_in_market"], 1)
