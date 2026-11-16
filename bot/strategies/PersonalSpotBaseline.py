"""H001: hourly, long-only SMA crossover for spot research and paper trading."""

import numpy as np
from freqtrade.strategy import IStrategy
from pandas import DataFrame


class PersonalSpotBaseline(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 100
    minimal_roi = {}
    stoploss = -0.05
    trailing_stop = False
    position_adjustment_enable = False

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 1},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 24,
                "trade_limit": 2,
                "stop_duration_candles": 6,
                "only_per_pair": False,
            },
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"].where(np.isfinite(dataframe["close"]))
        dataframe["sma20"] = close.rolling(20).mean()
        dataframe["sma50"] = close.rolling(50).mean()
        dataframe["sma_gap"] = dataframe["sma20"] - dataframe["sma50"]
        dataframe["warmed_up"] = close.rolling(self.startup_candle_count).count().eq(
            self.startup_candle_count
        )
        return dataframe

    def _valid_signal(self, dataframe: DataFrame):
        gap = dataframe["sma_gap"]
        volume = dataframe["volume"]
        return (
            dataframe["warmed_up"]
            & np.isfinite(gap)
            & np.isfinite(gap.shift())
            & np.isfinite(volume)
            & volume.gt(0)
        )

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        gap = dataframe["sma_gap"]
        entry = self._valid_signal(dataframe) & gap.gt(0) & gap.shift().le(0)
        dataframe["enter_long"] = entry.astype("int8")
        dataframe["enter_tag"] = "sma_cross_up"
        dataframe.loc[~entry, "enter_tag"] = None
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        gap = dataframe["sma_gap"]
        exit_signal = self._valid_signal(dataframe) & gap.lt(0) & gap.shift().ge(0)
        dataframe["exit_long"] = exit_signal.astype("int8")
        dataframe["exit_tag"] = "sma_cross_down"
        dataframe.loc[~exit_signal, "exit_tag"] = None
        return dataframe
