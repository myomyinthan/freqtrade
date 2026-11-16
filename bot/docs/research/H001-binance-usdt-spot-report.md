# H001 Historical Evaluation Report — Binance USDT Spot

Prepared: `2026-11-16`  
Status: **Technical validation PASSED · Economic screening FAILED · Untouched holdout SEALED**

## 1. Scope and Provenance

This report closes Milestone 2 (`B10`–`B13`) for registered hypothesis **H001** (`PersonalSpotBaseline`: closed-candle `1h` long-only `SMA20` / `SMA50` crossover, fixed `-0.05` stoploss, empty `minimal_roi`, `CooldownPeriod` 1 candle, global `StoplossGuard` after 2 stoplosses in 24 candles locking 6 candles).

| Item | Verified value |
| --- | --- |
| Venue & mode | `binance`, `spot`, `dry_run=true`, long-only (`can_short=false`, no DCA/pyramiding) |
| Universe | Static present-day spot whitelist: `BTC/USDT`, `ETH/USDT`, `SOL/USDT` (carries survivorship bias) |
| Paper wallet & sizing | `1000` USDT initial wallet, `50` USDT fixed stake (`5%`), `max_open_trades=2`, `tradable_balance_ratio=0.99` |
| Pinned engine | Freqtrade `2026.10`, commit `4cf0351e08d26e96a6429ef48103b726bb230cf8`, image `docker.io/freqtradeorg/freqtrade@sha256:1bb9a6b11a4dae39444331aa324b139dcd635f6a1c586ce9ecccac17994edc0c` (`linux/arm64`) |
| Frozen dataset range | `20240101-20261114` (`1h` and `5m` Feather, zero missing slots, zero duplicate timestamps, zero zero-volume candles) |
| `dataset_manifest_sha256` | `be44e132bb5531fb41a783a5e558f15845f059239f67cef286e92beac46c49aa` |
| `effective_config_sha256` | `bc8131a7e2465f73f632e72e3e17e239493712abb28b879b2aa0ffd10d84d95f` |
| `strategy_sha256` | `0f0ff5039fc0c65b935b005a26f7a939f64c1a00409b2b2472b7b3db039363b7` |
| Baseline fee assumption | `0.001` (`0.10%`) per side — provisional Binance regular-user spot taker rate (no VIP tier or BNB discount assumed) |
| Protections | Explicitly enabled (`--enable-protections --cache none`) on every backtest |
| Attempted variants | `1` (`PersonalSpotBaseline` as pre-registered; zero retuning, indicator additions, or parameter sweeps) |

## 2. Primary Chronological Split Results (`1.0×` baseline fee = `0.10%` per side)

Annualization follows Freqtrade's 365-day calendar compound convention (`CAGR %`). Each split starts from a fresh `1000` USDT wallet with pre-window candles used strictly for indicator warmup (`408` hours available before `train`). Open trades at window end are closed and labeled `force_exit` by the backtester.

| Metric | Training (`20240118–20250928`, 619d) | Validation (`20250928–20260422`, 206d) |
| --- | ---: | ---: |
| Run archive | `20261116T075829918939-train` | `20261116T075849925799-validation` |
| Net return / Net P&L | `-2.26%` (`-22.61` USDT) | `-5.09%` (`-50.93` USDT) |
| CAGR | `-1.34%` | `-8.89%` |
| Realized max drawdown | `8.11%` (`83.66` USDT) | `5.84%` (`58.91` USDT) |
| Daily wallet max drawdown | `8.71%` (`90.38` USDT) | `6.28%` (`63.54` USDT) |
| Completed + boundary trades | `361` (`0.58` / day) | `120` (`0.59` / day) |
| Average trade duration | `44.35` h (`1d 20h 21m`) | `42.08` h (`1d 18h 05m`) |
| Hours in market / Position-hours | `9,343` h (`62.9%` of window) / `16,012` h | `2,835` h (`57.3%` of window) / `5,050` h |
| Quote turnover | `35,942.59` USDT | `11,903.16` USDT |
| Estimated quote fees paid | `35.94` USDT | `11.90` USDT |
| Win rate | `32.69%` (`118` W / `243` L) | `27.50%` (`33` W / `87` L) |
| Average win / Average loss | `+2.32` USDT / `-1.22` USDT | `+1.35` USDT / `-1.10` USDT |
| Expectancy per trade | `-0.063` USDT | `-0.424` USDT |
| Profit factor | `0.92` | `0.47` |
| Exit counts (`sma_cross_down` / `stop_loss` / `force_exit`) | `311` / `48` / `2` (`-0.07` USDT) | `103` / `15` / `2` (`-0.58` USDT) |
| Cash benchmark (`USDT`) | `0.00%` | `0.00%` |
| Equal-weight buy-and-hold (net of `0.10%` entry/exit fee) | `+104.39%` | `-43.51%` |

Note on benchmark risk equivalence: `PersonalSpotBaseline` caps gross exposure at `2 × 50 = 100` USDT (`10%` of initial wallet) and was in the market ~`57%–63%` of hours, so `100%`-invested buy-and-hold is not risk-equivalent. Even scaled to a `10%` cash-backed allocation, passive spot exposure gained roughly `+10.4%` in training and lost `-4.35%` in validation, whereas H001 lost money in **both** windows (`-2.26%` in a rising market and `-5.09%` in a falling market).

### Per-Pair and Quarterly Contributions (USDT)

| Breakdown | Training (`20240118–20250928`) | Validation (`20250928–20260422`) |
| --- | --- | --- |
| `BTC/USDT` | `-4.02` USDT (`138` trades; B&H `+155.79%`) | `-9.37` USDT (`44` trades; B&H `-30.51%`) |
| `ETH/USDT` | `-32.10` USDT (`125` trades; B&H `+58.50%`) | `-13.19` USDT (`39` trades; B&H `-42.20%`) |
| `SOL/USDT` | `+13.50` USDT (`98` trades; B&H `+98.88%`) | `-28.37` USDT (`37` trades; B&H `-57.80%`) |
| Quarters | `2024-Q1` `+24.07`, `2024-Q2` `-40.23`, `2024-Q3` `+16.06`, `2024-Q4` `+10.09`, `2025-Q1` `-38.32`, `2025-Q2` `-19.01`, `2025-Q3` `+24.74` | `2025-Q4` `-31.60`, `2026-Q1` `-10.88`, `2026-Q2` `-8.46` (every validation month negative) |

## 3. Cost Stress, Intrabar Detail, and Walk-Forward Diagnostics

### Explicit Fee Multipliers and Post-Processed Adverse Fill Stress

Post-processed adverse fill costs (`5, 10, 25, 50` bps per side) deduct adverse fill movement on exported trades without re-simulating stop triggers, order feasibility, slot contention, or holding periods.

| Scenario | Training net return | Validation net return | Validation drawdown |
| --- | ---: | ---: | ---: |
| Baseline (`0.10%` fee/side) | `-2.26%` | `-5.09%` | `5.84%` |
| `1.5×` fee (`0.15%` fee/side) | `-4.06%` | `-5.69%` | `6.42%` |
| `2.0×` fee (`0.20%` fee/side) | `-5.86%` | `-6.28%` | `7.00%` |
| `5m` detail intrabar replay (`0.10%` fee/side) | not re-run | `-5.09%` (`120` trades) | `5.84%` |
| Baseline + `5` bps/side adverse fill | `-4.06%` | `-5.69%` | post-processed |
| Baseline + `10` bps/side adverse fill | `-5.86%` | `-6.28%` | post-processed |
| Baseline + `25` bps/side adverse fill | `-11.25%` | `-8.07%` | post-processed |
| Baseline + `50` bps/side adverse fill | `-20.23%` | `-11.04%` | post-processed |

### Pre-Registered 91-Day Walk-Forward Slices (First 80% Only)

| Slice | UTC range | Trades | Net P&L (USDT) | Net return | Market change | Account drawdown |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `walk-forward-1` | `20240718–20241017` | 48 | `+7.66` | `+0.77%` | `-6.93%` | `1.11%` |
| `walk-forward-2` | `20241017–20250116` | 53 | `+8.22` | `+0.82%` | `+37.73%` | `2.18%` |
| `walk-forward-3` | `20250116–20250417` | 59 | `-70.89` | `-7.09%` | `-35.09%` | `7.09%` |
| `walk-forward-4` | `20250417–20250717` | 56 | `+10.63` | `+1.06%` | `+61.79%` | `1.67%` |
| `walk-forward-5` | `20250717–20251016` | 50 | `-3.66` | `-0.37%` | `+7.75%` | `1.43%` |
| `walk-forward-6` | `20251016–20260115` | 54 | `-19.41` | `-1.94%` | `-17.44%` | `2.99%` |
| `walk-forward-7` | `20260115–20260416` | 51 | `-23.34` | `-2.33%` | `-31.21%` | `2.33%` |

## 4. Bias and Startup Verification (`B11`)

- **Lookahead analysis (`20261116T075849925821-validation`):** Found `169` candidate trades across the validation range and evaluated the configured target of `20` signals (`has_bias=False`, `biased_entry_signals=0`, `biased_exit_signals=0`, `biased_indicators` empty). Coverage caveat: `20 / 169` validation signals were re-simulated by the bias harness; prefix invariance across overlapping historical prefixes is additionally verified in `bot/tests/test_strategy_runtime.py`.
- **Recursive & indicator-only lookahead analysis:** Executed across startup candle counts `50`, `100` (strategy setting), `200`, and `400` on `BTC/USDT` (`20261116T075850083362-validation`), `ETH/USDT` (`20261116T075856567172-validation`), and `SOL/USDT` (`20261116T075901554812-validation`). Result: `0.000%` indicator variance and no indicator lookahead detected; `startup_candle_count = 100` is sufficient and readily supplied by Binance REST.

## 5. Gate Decision and Holdout Disposition (`B13`)

1. **Technical gate — PASS:** Reproducible pinned-container execution, audited gap-free Feather dataset, protections active, no lookahead or recursive drift detected on tested signals, and complete fee/fill accounting.
2. **Economic screening gate — FAIL:** Out-of-sample expectancy is negative (`-0.424` USDT/trade), validation profit factor is `0.47`, every validation pair and calendar month lost money, and training also lost `-2.26%` despite a `+105.79%` market advance due to whipsaw losses and fee drag (`35.94` USDT fees vs `-22.61` USDT net P&L). User drawdown and stressed-loss thresholds remain unset (`null`), which also precludes any economic pass claim.
3. **Untouched test (`20260422–20261114`) — PRESERVED SEALED:** Because H001 already failed validation unambiguously and was rejected as a live candidate without modification, the holdout window was intentionally **not opened**. Keeping `20260422–20261114` unconsumed preserves a clean out-of-sample final test for a future pre-registered hypothesis (`H002`).
4. **Operational next step:** Advance `PersonalSpotBaseline` into Milestone 3 **strictly as a labeled paper-only engineering fixture** to validate dry-run container execution, monitoring, entry pause, backup, and isolated restore. **No live trading is recommended or authorized.**
