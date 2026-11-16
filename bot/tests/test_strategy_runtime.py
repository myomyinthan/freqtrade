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


@skipIf(pd is None, "run in the pinned Freqtrade container")
class BreakoutH002Test(TestCase):
    def setUp(self):
        self.strategy = StrategyResolver.load_strategy({
            "strategy": "PersonalSpotBreakout",
            "strategy_path": str(Path(__file__).resolve().parents[1] / "strategies"),
            "user_data_dir": Path("/tmp"),
        })

    def signals(self, closes, highs=None, lows=None, volumes=None):
        n = len(closes)
        data = pd.DataFrame({
            "open": closes,
            "high": highs if highs is not None else [c + 0.5 for c in closes],
            "low": lows if lows is not None else [c - 0.5 for c in closes],
            "close": closes,
            "volume": volumes if volumes is not None else [10.0] * n,
        })
        data = self.strategy.populate_indicators(data, {})
        data = self.strategy.populate_entry_trend(data, {})
        return self.strategy.populate_exit_trend(data, {})

    def test_regime_filtered_breakout_and_channel_exit_without_conflicts(self):
        # Gentle uptrend for 240 bars so sma200 is rising, then high-volume 7d breakout, then 3d breakdown.
        closes = [100.0 + 0.05 * i for i in range(245)] + [130.0] + [128.0] * 10 + [95.0]
        vols = [10.0] * 245 + [25.0] + [10.0] * 10 + [15.0]
        frame = self.signals(closes, volumes=vols)
        self.assertEqual(int(frame.iloc[:240]["enter_long"].sum()), 0)
        self.assertEqual(int(frame.loc[245, "enter_long"]), 1)
        self.assertEqual(frame.loc[245, "enter_tag"], "donchian_breakout_up")
        self.assertEqual(int(frame.iloc[-1]["exit_long"]), 1)
        self.assertEqual(frame.iloc[-1]["exit_tag"], "donchian_channel_exit")
        self.assertFalse((frame["enter_long"] & frame["exit_long"]).any())
        self.assertNotIn("enter_short", frame)

    def test_blocks_bear_regime_low_volume_and_corrupted_bars(self):
        # Falling regime (sma200 falling): breakout bar must NOT enter.
        falling = [200.0 - 0.2 * i for i in range(245)] + [185.0]
        vols = [10.0] * 245 + [30.0]
        self.assertEqual(int(self.signals(falling, volumes=vols)["enter_long"].sum()), 0)

        # Rising regime with below-average volume on breakout bar: must NOT enter.
        rising = [100.0 + 0.05 * i for i in range(245)] + [130.0]
        low_vols = [10.0] * 245 + [5.0]
        self.assertEqual(int(self.signals(rising, volumes=low_vols)["enter_long"].sum()), 0)

        # NaN inside the 240-bar warmup resets warmed_up and blocks entry.
        bad = rising.copy()
        bad[120] = float("nan")
        self.assertEqual(int(self.signals(bad, volumes=vols)["enter_long"].sum()), 0)

    def test_prefixes_produce_identical_past_signals(self):
        closes = [100.0 + 0.05 * i for i in range(245)] + [130.0] + [129.0] * 15 + [90.0] * 5
        vols = [10.0] * 245 + [25.0] + [12.0] * 15 + [18.0] * 5
        full = self.signals(closes, volumes=vols)
        for end in (240, 246, 255, 263, 266):
            pd.testing.assert_frame_equal(
                self.signals(closes[:end], volumes=vols[:end]), full.iloc[:end],
            )


@skipIf(pd is None, "run in the pinned Freqtrade container")
class MacroBreakoutH003Test(TestCase):
    def setUp(self):
        self.strategy = StrategyResolver.load_strategy({
            "strategy": "PersonalSpotMacroBreakout",
            "strategy_path": str(Path(__file__).resolve().parents[1] / "strategies"),
            "user_data_dir": Path("/tmp"),
        })

    def signals(self, closes, volumes=None):
        n = len(closes)
        data = pd.DataFrame({
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": volumes if volumes is not None else [10.0] * n,
        })
        data = self.strategy.populate_indicators(data, {})
        data = self.strategy.populate_entry_trend(data, {})
        return self.strategy.populate_exit_trend(data, {})

    def test_macro_stack_entry_exit_and_short_bounce_rejection(self):
        # 405 rising bars so sma120 > sma360 and sma360 rising, then 14d high-volume breakout, then 4d breakdown.
        closes = [100.0 + 0.05 * i for i in range(405)] + [140.0] + [138.0] * 10 + [95.0]
        vols = [10.0] * 405 + [25.0] + [10.0] * 10 + [15.0]
        frame = self.signals(closes, volumes=vols)
        self.assertEqual(int(frame.iloc[:400]["enter_long"].sum()), 0)
        self.assertEqual(int(frame.loc[405, "enter_long"]), 1)
        self.assertEqual(frame.loc[405, "enter_tag"], "macro_donchian_up")
        self.assertEqual(int(frame.iloc[-1]["exit_long"]), 1)
        self.assertEqual(frame.iloc[-1]["exit_tag"], "macro_channel_exit")
        self.assertFalse((frame["enter_long"] & frame["exit_long"]).any())

        # Bear regime with 7-day (168h) dead-cat bounce must NOT enter while sma120 <= sma360 or < 14d high.
        bear_bounce = [200.0 - 0.25 * i for i in range(340)] + [115.0 + 0.1 * j for j in range(70)]
        bounce_vols = [10.0] * 409 + [30.0]
        self.assertEqual(int(self.signals(bear_bounce, volumes=bounce_vols)["enter_long"].sum()), 0)

    def test_prefixes_produce_identical_past_signals(self):
        closes = [100.0 + 0.05 * i for i in range(405)] + [140.0] + [138.0] * 12 + [90.0] * 4
        vols = [10.0] * 405 + [25.0] + [11.0] * 12 + [16.0] * 4
        full = self.signals(closes, volumes=vols)
        for end in (400, 406, 415, 420, 422):
            pd.testing.assert_frame_equal(
                self.signals(closes[:end], volumes=vols[:end]), full.iloc[:end],
            )
