"""H002: hourly, long-only regime-filtered 7d/3d Donchian spot breakout."""

import numpy as np
from freqtrade.strategy import IStrategy
from pandas import DataFrame


class PersonalSpotBreakout(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 240
    minimal_roi = {}
    stoploss = -0.08
    trailing_stop = False
    position_adjustment_enable = False

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,
                "trade_limit": 2,
                "stop_duration_candles": 12,
                "only_per_pair": False,
            },
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"].where(np.isfinite(dataframe["close"]))
        high = dataframe["high"].where(np.isfinite(dataframe["high"]))
        low = dataframe["low"].where(np.isfinite(dataframe["low"]))
        vol = dataframe["volume"].where(
            np.isfinite(dataframe["volume"]) & dataframe["volume"].ge(0)
        )

        valid_bar = close.notna() & high.notna() & low.notna() & vol.notna()
        dataframe["sma200"] = close.rolling(200).mean()
        dataframe["sma200_slope24"] = dataframe["sma200"] - dataframe["sma200"].shift(24)
        dataframe["prior_high_168"] = high.shift(1).rolling(168).max()
        dataframe["prior_low_72"] = low.shift(1).rolling(72).min()
        dataframe["prior_vol_sma24"] = vol.shift(1).rolling(24).mean()
        dataframe["warmed_up"] = (
            valid_bar.astype("int8")
            .rolling(self.startup_candle_count)
            .sum()
            .eq(self.startup_candle_count)
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        vol = dataframe["volume"]
        sma200 = dataframe["sma200"]
        slope = dataframe["sma200_slope24"]
        high168 = dataframe["prior_high_168"]
        vol24 = dataframe["prior_vol_sma24"]

        entry = (
            dataframe["warmed_up"]
            & np.isfinite(close)
            & np.isfinite(vol)
            & np.isfinite(sma200)
            & np.isfinite(slope)
            & np.isfinite(high168)
            & np.isfinite(vol24)
            & vol.gt(0)
            & vol.gt(vol24)
            & close.gt(sma200)
            & slope.gt(0)
            & close.gt(high168)
        )
        dataframe["enter_long"] = entry.astype("int8")
        dataframe["enter_tag"] = "donchian_breakout_up"
        dataframe.loc[~entry, "enter_tag"] = None
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        vol = dataframe["volume"]
        low72 = dataframe["prior_low_72"]

        exit_signal = (
            dataframe["warmed_up"]
            & np.isfinite(close)
            & np.isfinite(vol)
            & np.isfinite(low72)
            & vol.gt(0)
            & close.lt(low72)
        )
        dataframe["exit_long"] = exit_signal.astype("int8")
        dataframe["exit_tag"] = "donchian_channel_exit"
        dataframe.loc[~exit_signal, "exit_tag"] = None
        return dataframe
