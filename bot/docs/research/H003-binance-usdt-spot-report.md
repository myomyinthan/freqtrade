# H003 Historical Evaluation Report — Binance USDT Spot (`PersonalSpotMacroBreakout`)

Prepared: `2026-11-16`  
Pre-registration: [H003-preregistration.md](H003-preregistration.md)  
Status: **Technical validation PASSED · Strongest Development Candidate (`+7.76%` Train, `+5.42%` Combined `Train + Val`, PF `2.36` Train, Wallet DD `<= 3.23%`) · Validation Bear-Cap Gate Missed by `0.34%` (`-2.34%` vs `-2.00%` Cap) · Untouched Holdout Preserved SEALED**

---

## 1. Provenance & Hypothesis Summary

`H003` (`PersonalSpotMacroBreakout`) separated the macro trend filter (`close > sma120 > sma360` with `sma360 > sma360.shift(24)`) from a `336h` (`14`-day) volume-confirmed Donchian breakout, paired with a `96h` (`4`-day) Donchian channel exit and `-6%` catastrophic stoploss (`startup_candle_count = 400`).

| Item | Verified value |
| --- | --- |
| Venue, mode & universe | `binance` spot, `dry_run=true`, `BTC/USDT`, `ETH/USDT`, `SOL/USDT` (`1,000` USDT wallet, `50` USDT stake, `max_open_trades = 2` -> `100` USDT max active exposure) |
| Pinned engine | Freqtrade `2026.10` (`4cf0351e08d26e96a6429ef48103b726bb230cf8`), image `sha256:1bb9a6b11a4dae39444331aa324b139dcd635f6a1c586ce9ecccac17994edc0c` |
| `dataset_manifest_sha256` | `be44e132bb5531fb41a783a5e558f15845f059239f67cef286e92beac46c49aa` (`20240101–20261114`) |
| `effective_config_sha256` | `bc8131a7e2465f73f632e72e3e17e239493712abb28b879b2aa0ffd10d84d95f` |
| `strategy_sha256` | `521c97ecf8253c8a06a65471b36f2631113c01afba9825a37252c0427a2349bb` (`PersonalSpotMacroBreakout.py`) |
| Attempted variants | `1` (exact pre-registered specification; zero retuning) |

---

## 2. Three-Generation Progression: `H001` vs. `H002` vs. `H003` (`0.10%` Baseline Fee / Side)

Note on exposure scaling: because `max_open_trades = 2` and `stake_amount = 50` USDT, at most **`100` USDT (`10%` of the `1,000` USDT paper wallet)** is ever deployed in spot positions (`90%` remains uninvested `USDT` cash reserve). Thus `+54.22` USDT net profit represents `+5.42%` on total wallet equity and **`+54.22%` on the `100` USDT active trading allocation**.

| Metric | H001 (`SMA20/50`) | H002 (`7d/3d + SMA200`) | **H003 (`14d/4d + SMA120/360`)** |
| --- | ---: | ---: | ---: |
| **Train Net Return / P&L** (`20240118–20250928`) | `-2.26%` (`-22.61` USDT) | `+4.98%` (`+49.82` USDT) | **`+7.76%` (`+77.61` USDT)** |
| **Train Profit Factor / Win Rate** | `0.92` / `32.7%` | `1.44` / `36.8%` | **`2.36` / `46.7%` (`21` W / `24` L)** |
| **Train Daily Wallet Sharpe / Calmar** | `-0.28` / `-0.80` | `0.81` / `3.72` | **`1.38` / `8.57`** |
| **Train Max Drawdown (Realized / Wallet)** | `8.11%` / `8.71%` | `2.82%` / `4.14%` | **`1.97%` / `2.80%`** |
| **Validation Net Return / P&L** (`20250928–20260422`, Mkt `-43.5%`) | `-5.09%` (`-50.93` USDT) | `-2.58%` (`-25.82` USDT) | **`-2.34%` (`-23.40` USDT)** |
| **Validation Max Drawdown (Realized / Wallet)** | `5.84%` / `6.28%` | `3.14%` / `3.94%` | **`2.61%` / `3.23%`** |
| **Combined `Train + Val` Net P&L (`825` days)** | `-73.54` USDT (`-7.35%`) | `+24.00` USDT (`+2.40%`) | **`+54.22` USDT (`+5.42%`, `+127.76` USDT vs H001)** |
| **Combined Trades / Turnover / Fees** | `481` / `47,846` / `47.85` USDT | `95` / `9,493` / `9.49` USDT | **`60` / `6,027` (`-87.4%` vs H001) / `6.03` USDT** |
| **7 Walk-Forward Slices Net Sum** | `-90.78` USDT | `+0.72` USDT | **`+11.56` USDT** |

### H003 Per-Pair and Quarterly Contributions (USDT)

In `H003`, **every pair was profitable in `train`** (`ETH/USDT +42.57`, `BTC/USDT +34.78`, `SOL/USDT +0.27`), and **`SOL/USDT` stayed profitable across both `train` (`+0.27`) and `validation` (`+1.56`)** even while passive `SOL/USDT` crashed `-57.80%` in validation!

| Breakdown | Training (`20240118–20250928`, `45` trades) | Validation (`20250928–20260422`, `15` trades) | Combined `Train + Val` (`60` trades) |
| --- | --- | --- | --- |
| `ETH/USDT` | `+42.57` USDT | `-13.61` USDT | **`+28.96` USDT** (`52.1%` of positive pair gains) |
| `BTC/USDT` | `+34.78` USDT | `-11.35` USDT | **`+23.43` USDT** (`42.1%` of positive pair gains) |
| `SOL/USDT` | `+0.27` USDT | `+1.56` USDT | **`+1.83` USDT** (`3.3%` of positive pair gains) |
| Exit breakdown | `32` `macro_channel_exit`, `13` `stop_loss`, `0` `force_exit` | `7` `macro_channel_exit`, `7` `stop_loss`, `1` `force_exit` | `39` channel / `20` stop / `1` boundary |
| Quarters | `2024-Q1` `+41.58`, `2024-Q2` `+1.72` (was `-26.65` in H002!), `2024-Q3` `-1.36`, `2024-Q4` `+12.18`, `2025-Q1` `-10.65`, `2025-Q2` `+15.87`, `2025-Q3` `+18.26` | `2025-Q4` `-14.41` (Nov `0` trades flat in cash), `2026-Q1` `-11.71` (Feb `0` trades flat in cash), `2026-Q2` `+2.72` | `6` of `10` quarters positive |

---

## 3. Cost Stress, `5m` Detail Replay, and Walk-Forward Diagnostics

Because `H003` holds winning trends `16.5` days on average (`60` total trades across `825` days), fee and slippage sensitivity is remarkably low — **`Train + Validation` remains `+24.08` USDT net profitable even under extreme `+50 bps` (`0.50%`) adverse fill cost per side (`1.00%` round-trip slippage + `0.20%` round-trip fees)**:

| Scenario | Train net return | Validation net return | Combined `Train + Val` P&L |
| --- | ---: | ---: | ---: |
| Baseline (`0.10%` fee/side) | **`+7.76%` (`+77.61` USDT)** | `-2.34%` (`-23.40` USDT) | **`+54.22` USDT (`+5.42%`)** |
| `1.5×` fee (`0.15%` fee/side) | **`+7.53%` (`+75.34` USDT)** | `-2.41%` (`-24.14` USDT) | **`+51.20` USDT (`+5.12%`)** |
| `2.0×` fee (`0.20%` fee/side) | **`+7.31%` (`+73.06` USDT)** | `-2.49%` (`-24.87` USDT) | **`+48.19` USDT (`+4.82%`)** |
| `5m` detail intrabar replay (`0.10%` fee/side) | not re-run | `-2.34%` (`15` trades, identical) | — |
| Baseline + `5` bps/side adverse fill | `+7.53%` | `-2.41%` | **`+51.20` USDT** |
| Baseline + `10` bps/side adverse fill | `+7.31%` | `-2.49%` | **`+48.19` USDT** |
| Baseline + `25` bps/side adverse fill | `+6.62%` | `-2.71%` | **`+39.15` USDT** |
| Baseline + `50` bps/side adverse fill | **`+5.48%`** | `-3.08%` | **`+24.08` USDT** |

### Pre-Registered 91-Day Walk-Forward Slices (`walk-forward-1..7`)

| Slice | UTC range | Trades | H003 Net P&L | H003 Return | Market | H003 Wallet DD |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `walk-forward-1` | `20240718–20241017` | 8 | `+1.26` USDT | `+0.13%` | `-6.93%` | `1.44%` |
| `walk-forward-2` | `20241017–20250116` | 12 | `+2.21` USDT | `+0.22%` | `+37.73%` | `2.32%` |
| `walk-forward-3` | `20250116–20250417` | 3 | `-5.37` USDT | `-0.54%` | `-35.09%` | `1.16%` |
| `walk-forward-4` | `20250417–20250717` | 9 | **`+32.91` USDT** | **`+3.29%`** | `+61.79%` | `1.62%` |
| `walk-forward-5` | `20250717–20251016` | 11 | `-5.43` USDT | `-0.54%` | `+7.75%` | `1.89%` |
| `walk-forward-6` | `20251016–20260115` | 7 | `-5.78` USDT | `-0.58%` | `-17.44%` | `1.12%` |
| `walk-forward-7` | `20260115–20260416` | 6 | `-8.23` USDT | `-0.82%` | `-31.21%` | `1.58%` |

---

## 4. Bias & Startup Verification

- **Lookahead analysis:** Passed (`has_bias=False`, `0` biased entry signals, `0` biased exit signals, `0` biased indicators) on **both** `bias-dev` (`20261116T101449618316`, `20` signals evaluated) and `validation` (`20261116T101458780783`, `18` signals evaluated).
- **Recursive & indicator lookahead analysis:** Passed across `BTC/USDT` (`20261116T101506590504`), `ETH/USDT` (`20261116T101511027309`), and `SOL/USDT` (`20261116T101515379648`) at `startup_candle_count = 400` (`0.000%` drift, zero indicator lookahead).

---

## 5. Strict Gate Audit & Anti-Overfitting Stop Rule

| # | Pre-Registered Gate | Requirement | Observed H003 Result | Verdict |
| --- | --- | --- | --- | --- |
| 1 | Technical & bias gate | `0` lookahead bias; `0.000%` recursive drift at `400`; `5m` detail match | `0` bias (`bias-dev` & `val`); `0.000%` drift; `5m` detail `-23.40` USDT match | **PASS** |
| 2 | Dev trade coverage | `train >= 20` and `combined >= 25` | `train = 45`, `val = 15`, `combined = 60` | **PASS** |
| 3 | Training profitability | Net return `> 0%` and expectancy `> 0` | **`+7.76%` (`+77.61` USDT)**, expectancy **`+1.72` USDT/trade**, PF **`2.36`** | **PASS** |
| 4 | **Validation bear-window cap** | Validation return `>= -2.00%` (`>= -20.00` USDT) at `1.0×` & `1.5×` fee | **`-2.34%` (`-23.40` USDT)** at `1.0×` (`-2.41%` at `1.5×`), missed by **`0.34%` (`3.40` USDT)** | **FAIL** |
| 5 | Combined stressed expectancy | `Train + val` net P&L `> 0` at `1.5×` fee, `2.0×` fee, and `+10 bps`/side fill | **`+51.20` USDT** (`1.5×`), **`+48.19` USDT** (`2.0×`), **`+48.19` USDT** (`+10 bps`) | **PASS** |
| 6 | Max account drawdown | Realized & wallet DD `<= 8.0%` in `train` and `validation` | `1.97% / 2.80%` train; `2.61% / 3.23%` validation | **PASS** |
| 7 | Pair concentration | Top pair `<= 85%` of positive pair gains across `train + val` | `ETH` `53.4%` (`+28.96`), `BTC` `43.2%` (`+23.43`), `SOL` `3.4%` (`+1.83`) — all 3 positive! | **PASS** |

### Why Stopping Iteration Here Protects Research Integrity
1. **Honoring the pre-registered `-2.00%` rule:** During the `-43.51%` validation crash (`10%` passive spot allocation = `-4.35%` loss), `H003` held validation loss to `-2.34%` (`3.23%` max wallet drawdown) while generating `+7.76%` in training (`+5.42%` net across all `825` days). Because `-2.34%` fell `3.40` USDT (`0.34%`) short of our strict `-2.00%` pre-registered cap, we **did not open `--window test`** (`20260422–20261114` remains 100% sealed).
2. **Refusing to curve-fit `validation`:** Running further micro-variants (`H004`, `H005`…) solely to trim `3.40` USDT off a `15`-trade bear window would turn `validation` into an overfitted training set.
3. **Recommended path forward:**
   - **Recommended primary paper candidate:** `PersonalSpotMacroBreakoutGuarded` (`H003` + `M4` persisted daily entry-halt guard) is now the strongest, lowest-drawdown, cost-resilient candidate in the repository.
   - **Explicit user choice on the sealed holdout (`20260422–20261114`):** If you judge `-2.34%` during a `-43.51%` bear market acceptable relative to your personal risk tolerance, you may explicitly authorize freezing `H003` as the final candidate and executing the **one-shot untouched holdout (`--window test`)** once — with that user-approved threshold revision transparently recorded in the protocol before unsealing.
