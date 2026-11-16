# Pre-Registration — Hypothesis H003 (`PersonalSpotMacroBreakout`)

Registered: `2026-11-16` (prior to any `H003` backtest execution)  
Dataset scope: Frozen `binance` `USDT` spot dataset `20240101–20261114` (`dataset_manifest_sha256 = be44e132bb5531fb41a783a5e558f15845f059239f67cef286e92beac46c49aa`)  
Effective config SHA-256: `bc8131a7e2465f73f632e72e3e17e239493712abb28b879b2aa0ffd10d84d95f`  
Registered `PersonalSpotMacroBreakout.py` SHA-256: `521c97ecf8253c8a06a65471b36f2631113c01afba9825a37252c0427a2349bb`  
Untouched holdout (`20260422–20261114`): **Unconsumed prior to registration (`0` `untouched-*` runs exist)**

## 1. Structural Hypothesis from H002 Post-Mortem

`H002` (`PersonalSpotBreakout`) passed `6` of `7` pre-registered gates (`+4.98%` train, `+2.40%` combined `train + validation`, `<= 4.14%` wallet drawdown), and missed only the `-2.00%` validation bear-window cap (`-2.58%` across `19` validation trades) for two structural reasons:

1. **Horizon collision between breakout and regime filter:** `H002` paired a `168h` (`7`-day) breakout with a `200h` (`8.3`-day) moving average. Because both look back roughly one week, a `6–8` day bear-market short squeeze simultaneously broke the `7`-day high and turned `SMA200` upward, admitting `19` counter-trend bull traps during the `-43.51%` validation drawdown.
2. **Wide `-8%` bull-trap giveback:** The `4` validation stoploss exits at `-8.18%` accounted for `-16.36 USDT` (`63%` of `H002`'s entire validation loss).

`H003` tests whether separating the **macro trend filter (`360h` / 15-day rising SMA aligned below `120h` / 5-day SMA)** from a **two-week (`336h` / 14-day) volume-confirmed Donchian breakout**, paired with a **`96h` (4-day) channel exit** and **`-6%` stoploss**, preserves sustained multi-week uptrends while keeping spot capital in `USDT` cash during bear-market dead-cat bounces.

## 2. Fixed Specification of H003 (`PersonalSpotMacroBreakout`)

Maximum allowed variants in this registration: **`1`** (zero parameter sweeps or post-hoc threshold edits).

| Rule | Fixed H003 Specification |
| --- | --- |
| Mode & timeframe | Long-only spot (`can_short = False`), `1h` closed candles (`process_only_new_candles = True`), no DCA or pyramiding. |
| Warmup | `startup_candle_count = 400` (`16.67` days; max indicator dependency `360 + 24 = 384 <= 400`, covered by the `408h` pre-train warmup in `20240101–20261114`). Zero signals before `400` consecutive valid finite bars. |
| Dual-horizon macro regime filter | `close > sma120`, `sma120 > sma360`, and `sma360 > sma360.shift(24)` (`15`-day average strictly rising over the prior `24h` and `5`-day average stacked above it). |
| Breakout entry (`macro_donchian_up`) | Closed `1h` candle breaks strictly above the prior `336` completed hours' (`14`-day) highest high (`close > high.shift(1).rolling(336).max()`) with positive volume strictly above the prior `24` completed hours' mean volume (`volume > volume.shift(1).rolling(24).mean()`) while the macro regime filter holds. |
| Channel exit (`macro_channel_exit`) | Closed `1h` candle breaks strictly below the prior `96` completed hours' (`4`-day) lowest low (`close < low.shift(1).rolling(96).min()`), with finite inputs and positive volume. Mutually exclusive with entry (`max(high[t-336..t-1]) >= min(low[t-96..t-1])`). |
| Catastrophic stoploss & ROI | Fixed stoploss `-0.06` (`-6%` on a `50 USDT` slot = `0.30%` nominal of `1,000 USDT` wallet); `minimal_roi = {}`; `trailing_stop = False`. |
| Protections | `CooldownPeriod` (`2` candles per pair); global `StoplossGuard` (`2` stoploss exits within `48` candles -> lock entries for `12` candles). |
| Universe & sizing | Unchanged: `BTC/USDT`, `ETH/USDT`, `SOL/USDT`; `1,000 USDT` paper wallet; `50 USDT` fixed stake (`max_open_trades = 2`). |

## 3. Pre-Registered Screening Gates & One-Shot Holdout Rule

Windows and cost scenarios are identical to `H001` and `H002` (`train`: `20240118–20250928`; `validation`: `20250928–20260422`; `bias-dev`: `20240118–20260422`; `walk-forward-1..7`; sealed `test`: `20260422–20261114`).

All **7** gates below must pass on `train` / `validation` / `bias-dev` before unsealing `test`:

1. **Technical & bias gate:** Zero lookahead bias on exercised `bias-dev` signals (`>= 20` signals evaluated), `0.000%` recursive variance at `startup_candle = 400` across `BTC/USDT`, `ETH/USDT`, and `SOL/USDT`, prefix invariance in unit tests, and deterministic `5m` detail validation replay.
2. **Development trade coverage gate:** At least `20` closed trades in `train` and `>= 25` combined trades across `train + validation` (low trade count in the `-43.51%` bear `validation` window is expected and desirable for a long-only cash filter, provided `bias-dev` exercises `>= 20` signals for lookahead verification).
3. **Training profitability gate:** Positive net return (`> 0%`) and positive trade expectancy (`> 0` USDT/trade) on `train` at baseline `0.10%` fee/side.
4. **Validation bear-regime protection gate:** Validation net return `>= -2.00%` (`>= -20.00 USDT`) at baseline `0.10%` fee/side **and** `>= -2.00%` at `1.5×` (`0.15%`/side) stressed fee during the `-43.51%` bear window.
5. **Combined stressed expectancy gate:** Strictly positive combined `train + validation` net P&L (`> 0` USDT) under `1.5×` (`0.15%`/side) fee, `2.0×` (`0.20%`/side) fee, and `+10 bps`/side post-processed adverse fill movement.
6. **Drawdown gate:** Realized and daily wallet max drawdown `<= 8.0%` (`0.08`) in both `train` and `validation`.
7. **Concentration gate:** No single pair exceeding `85%` of total positive pair profits across `train + validation`.

**One-shot holdout rule (`B13`):** If and only if **all 7 gates above pass**, execute `--window test` (`20260422–20261114`) **exactly once** (`untouched-be44e132bb55-20260422-20261114`) at baseline `0.10%` fee and record the unedited out-of-sample result (positive net return and drawdown `<= 8.0%` required to pass the final economic gate). If any gate above fails, keep `test` sealed.
