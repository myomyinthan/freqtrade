# Pre-Registration — Hypothesis H002 (`PersonalSpotBreakout`)

Registered: `2026-11-16` (prior to any `H002` backtest execution)  
Dataset scope: Frozen `binance` `USDT` spot dataset `20240101–20261114` (`dataset_manifest_sha256 = be44e132bb5531fb41a783a5e558f15845f059239f67cef286e92beac46c49aa`)  
Effective config SHA-256: `bc8131a7e2465f73f632e72e3e17e239493712abb28b879b2aa0ffd10d84d95f`  
Registered `PersonalSpotBreakout.py` SHA-256: `56b31cdfe8d87aa0148af2fe89ae84b9cab09a100be398ff888cbfe1dd5956ea`  
Untouched holdout (`20260422–20261114`): **Unconsumed prior to registration**

## 1. Motivation from H001 Post-Mortem

`H001` (`PersonalSpotBaseline`: `1h` `SMA20`/`SMA50` crossover with `-0.05` stoploss) failed on `train` (`-2.26%`, `361` trades, `35.94 USDT` fees) and `validation` (`-5.09%`, `120` trades, profit factor `0.47`) for three structural reasons observable strictly within `train` and `validation`:

1. **Excessive 1h crossover churn:** `481` total trades across `train + validation` generated `47,845.75 USDT` of turnover against a `100 USDT` two-slot capital cap, losing ~`47.85 USDT` to fees alone.
2. **Unfiltered counter-trend longs in bear regimes:** Long-only spot entries on short-horizon `20h`/`50h` crosses repeatedly bought bear-market bounces during `2024-Q2`, `2025-Q1`, and the `-43.34%` `validation` drawdown.
3. **Premature `-5%` stoploss clips:** `63` fixed `-5%` stoploss exits (`-163.05 USDT`) truncated ordinary multi-hour crypto volatility while lagging `SMA` exits returned modest gains during sideways ranges.

## 2. Fixed Specification of H002 (`PersonalSpotBreakout`)

Maximum allowed variants in this registration: **`1`** (exact fixed rules below; zero parameter sweeps, zero indicator additions after viewing results).

| Rule | Fixed H002 Specification |
| --- | --- |
| Mode & timeframe | Long-only spot (`can_short = False`), `1h` closed candles (`process_only_new_candles = True`), no DCA or position adjustment. |
| Warmup | `startup_candle_count = 240` (`10` days of finite `1h` candles; `408h` pre-train warmup available in frozen dataset). Zero signals emitted before `240` finite closes, highs, lows, and volumes. |
| Regime filter | Close strictly above `200h` simple moving average (`close > sma200`) **and** `200h` average rising over the past day (`sma200 > sma200.shift(24)`). Sits in `USDT` cash during sustained downtrends. |
| Breakout entry (`donchian_breakout_up`) | Closed `1h` candle breaks strictly above the prior `168` completed hours' (7-day) highest high (`close > high.shift(1).rolling(168).max()`) with positive volume strictly above the prior `24` completed hours' mean volume (`volume > volume.shift(1).rolling(24).mean()`) while the regime filter holds. |
| Signal exit (`donchian_channel_exit`) | Closed `1h` candle breaks strictly below the prior `72` completed hours' (3-day) lowest low (`close < low.shift(1).rolling(72).min()`), with finite inputs and positive volume. Because `max(high[t-168..t-1]) >= min(low[t-72..t-1])`, entry and exit cannot fire on the same candle. |
| Safety stop & ROI | Fixed catastrophic stoploss `-0.08` (`-8%` nominal on a `50 USDT` slot = `0.40%` of `1,000 USDT` wallet); `minimal_roi = {}`; `trailing_stop = False`. |
| Protections | `CooldownPeriod` (`2` candles per pair); global `StoplossGuard` (`2` stoploss exits within `48` candles -> lock entries for `12` candles). |
| Universe & sizing | Unchanged from H001: `BTC/USDT`, `ETH/USDT`, `SOL/USDT`; `1,000 USDT` paper wallet; `50 USDT` fixed stake (`max_open_trades = 2`). |

## 3. Pre-Registered Screening Gates & Holdout Rule

All windows match H001 (`train`: `20240118–20250928`; `validation`: `20250928–20260422`; `walk-forward-1..7`; sealed `test`: `20260422–20261114`; baseline fee `0.001` per side, stressed at `1.5× = 0.0015` and `2.0× = 0.002`, plus `5/10/25/50` bps per-side adverse fill post-processing and `5m` detail replay).

1. **Technical gate:** Zero lookahead bias on exercised validation signals, `0.000%` recursive variance at `>= 240` startup candles (`240` and `400`), prefix invariance across historical prefixes, and deterministic repeat runs.
2. **Sample coverage gate:** At least `25` closed trades in `train` and at least `8` closed trades in `validation` (or if validation is predominantly a bear regime where the cash filter intentionally stays flat, combined `train + validation >= 35` trades with explicit low-validation-sample labeling; `0` validation trades marks validation bias/expectancy **INCONCLUSIVE**).
3. **Economic screening gates (must ALL hold before unsealing `20260422–20261114`):**
   - Positive net return and positive expectancy (`> 0` USDT/trade) on `train` at baseline `0.10%` fee.
   - Non-negative or materially improved validation expectancy (`>= 0` USDT/trade, or strictly positive combined `train + validation` net P&L after `1.5×` (`0.15%`/side) stressed fees with validation loss no worse than `-2.0%` of wallet during the `-43.5%` bear window).
   - Account max drawdown `<= 8.0%` (`0.08`) in both `train` and `validation`.
   - Positive net return retained under `+10 bps`/side adverse fill post-processing across `train + validation` combined, and no single pair exceeding `85%` of total positive profit while both other pairs lose materially (`< -1.5%` of wallet).
4. **One-shot holdout rule:** Only if `H002` passes the technical and economic screening gates above will `--window test` (`20260422–20261114`) be executed **exactly once** with zero modifications. Otherwise, `H002` is recorded as failed/inconclusive and the holdout stays sealed.
