from pathlib import Path
from unittest import TestCase, skipIf

try:
    import pandas as pd
    from freqtrade.enums import ExitType
    from freqtrade.persistence import LocalTrade
    from freqtrade.resolvers import StrategyResolver
except ImportError:
    pd = None


@skipIf(pd is None, "run in the pinned Freqtrade container")
class BaselineTest(TestCase):
    def setUp(self):
        self.strategy = StrategyResolver.load_strategy({
            "strategy": "PersonalSpotBaseline",
            "strategy_path": str(Path(__file__).resolve().parents[1] / "strategies"),
            "user_data_dir": Path("/tmp"),
        })

    def signals(self, prices, volumes=None):
        data = pd.DataFrame({"close": prices, "volume": volumes if volumes is not None else 1.0})
        data = self.strategy.populate_indicators(data, {})
        data = self.strategy.populate_entry_trend(data, {})
        return self.strategy.populate_exit_trend(data, {})

    def test_crosses_equal_average_once_in_each_direction(self):
        prices = [10.0] * 100 + [12.0] * 20 + [5.0] * 20
        data = self.signals(prices)
        self.assertEqual(data.index[data.enter_long.eq(1)].tolist(), [100])
        self.assertEqual(int(data.exit_long.sum()), 1)
        self.assertEqual(data.loc[100, "enter_tag"], "sma_cross_up")
        self.assertFalse((data.enter_long & data.exit_long).any())
        self.assertNotIn("enter_short", data)

    def test_needs_warmup_finite_inputs_and_current_volume(self):
        self.assertEqual(int(self.signals([10.0] * 98 + [12.0]).enter_long.sum()), 0)
        prices = [10.0] * 100 + [12.0]
        self.assertEqual(int(self.signals(prices, [1.0] * 100 + [0.0]).enter_long.sum()), 0)
        for bad in (float("nan"), float("inf")):
            corrupt = prices.copy()
            corrupt[75] = bad
            self.assertEqual(int(self.signals(corrupt).enter_long.sum()), 0)

    def test_prefixes_produce_identical_past_signals(self):
        prices = [10.0] * 100 + [12.0] * 20 + [5.0] * 20 + [15.0] * 25
        full = self.signals(prices)
        for end in (100, 101, 125, 143, 160):
            pd.testing.assert_frame_equal(self.signals(prices[:end]), full.iloc[:end])

    def test_engine_exit_signal_precedes_stop_and_no_roi_exit(self):
        opened = pd.Timestamp("2024-01-01", tz="UTC").to_pydatetime()
        now = pd.Timestamp("2024-01-02", tz="UTC").to_pydatetime()
        trade = LocalTrade(pair="BTC/USD", open_rate=100, amount=1, stake_amount=100,
                           open_date=opened, fee_open=0, fee_close=0, is_short=False)
        exits = self.strategy.should_exit(trade, 94, now, enter=False, exit_=True)
        self.assertEqual([event.exit_type for event in exits], [ExitType.EXIT_SIGNAL, ExitType.STOP_LOSS])
        exits = self.strategy.should_exit(trade, 110, now, enter=False, exit_=False)
        self.assertEqual(exits, [])
