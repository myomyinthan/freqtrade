# H002 Historical Evaluation Report — Binance USDT Spot (`PersonalSpotBreakout`)

Prepared: `2026-11-16`  
Pre-registration: [H002-preregistration.md](H002-preregistration.md)  
Status: **Technical validation PASSED · Training & Combined Dev Net Positive · Validation Bear-Cap Gate MISSED (`-2.58%` vs `-2.00%` cap) · Untouched Holdout SEALED**

---

## 1. Provenance & Hypothesis Summary

`H002` (`PersonalSpotBreakout`) tested whether filtering out counter-trend bear regimes (`close > sma200` and `sma200 > sma200.shift(24)`) and trading lower-frequency `168h` (7-day) high-volume Donchian breakouts with a `72h` (3-day) channel exit and `-8%` stoploss would eliminate `H001`'s crossover churn and negative expectancy.

| Item | Verified value |
| --- | --- |
| Venue, mode & universe | `binance` spot, `dry_run=true`, `BTC/USDT`, `ETH/USDT`, `SOL/USDT` (`1,000` USDT wallet, `50` USDT stake, `max_open_trades = 2`) |
| Pinned engine | Freqtrade `2026.10` (`4cf0351e08d26e96a6429ef48103b726bb230cf8`), image `sha256:1bb9a6b11a4dae39444331aa324b139dcd635f6a1c586ce9ecccac17994edc0c` |
| `dataset_manifest_sha256` | `be44e132bb5531fb41a783a5e558f15845f059239f67cef286e92beac46c49aa` (`20240101–20261114`) |
| `effective_config_sha256` | `bc8131a7e2465f73f632e72e3e17e239493712abb28b879b2aa0ffd10d84d95f` |
| `strategy_sha256` | `56b31cdfe8d87aa0148af2fe89ae84b9cab09a100be398ff888cbfe1dd5956ea` (`PersonalSpotBreakout.py`) |
| Attempted variants | `1` (exact pre-registered specification; zero retuning) |

---

## 2. Head-to-Head Comparison: `H001` vs. `H002` (`0.10%` Baseline Fee / Side)

| Metric | H001 Train | **H002 Train** (`20240118–20250928`) | H001 Validation | **H002 Validation** (`20250928–20260422`) |
| --- | ---: | ---: | ---: | ---: |
| Run archive | `20261116T075829918939` | `20261116T095612492931` | `20261116T075849925799` | `20261116T095614685588` |
| Net return / Net P&L | `-2.26%` (`-22.61` USDT) | **`+4.98%` (`+49.82` USDT)** | `-5.09%` (`-50.93` USDT) | **`-2.58%` (`-25.82` USDT)** |
| Combined `train + val` net P&L | — | — | `-73.54` USDT (`-7.35%`) | **`+24.00` USDT (`+2.40%`)** |
| CAGR | `-1.34%` | **`+2.91%`** | `-8.89%` | `-4.55%` |
| Realized max drawdown | `8.11%` (`83.66` USDT) | **`2.82%` (`29.60` USDT)** | `5.84%` (`58.91` USDT) | **`3.14%` (`31.43` USDT)** |
| Daily wallet max drawdown | `8.71%` (`90.38` USDT) | **`4.14%` (`43.92` USDT)** | `6.28%` (`63.54` USDT) | **`3.94%` (`39.75` USDT)** |
| Closed trades | `361` (`2` left open) | **`76` (`0` left open)** | `120` (`2` left open) | **`19` (`0` left open)** |
| Average trade duration | `44.35` h | `152.45` h (`6d 08h`) | `42.08` h | `129.74` h (`5d 09h`) |
| Hours in market / Position-hours | `9,343` h / `16,012` h | `7,127` h (`48.0%`) / `11,586` h | `2,835` h / `5,050` h | `1,577` h (`31.9%`) / `2,465` h |
| Quote turnover | `35,942.59` USDT | **`7,623.76` USDT (`-78.8%`)** | `11,903.16` USDT | **`1,868.93` USDT (`-84.3%`)** |
| Estimated quote fees paid | `35.94` USDT | **`7.62` USDT** | `11.90` USDT | **`1.87` USDT** |
| Win rate | `32.69%` | **`36.84%` (`28` W / `48` L)** | `27.50%` | `31.58%` (`6` W / `13` L) |
| Average win / Average loss | `+2.32` / `-1.22` USDT | **`+5.85` / `-2.38` USDT** | `+1.35` / `-1.10` USDT | `+1.58` / `-2.71` USDT |
| Expectancy per trade | `-0.063` USDT | **`+0.656` USDT** | `-0.424` USDT | `-1.359` USDT |
| Profit factor | `0.92` | **`1.44`** | `0.47` | `0.27` |
| Exit counts (channel / stop / force) | `311` / `48` / `2` | **`65` (`+94.69` USDT) / `11` (`-44.87` USDT) / `0`** | `103` / `15` / `2` | **`15` (`-9.46` USDT) / `4` (`-16.36` USDT) / `0`** |
| Equal-weight buy & hold | `+104.39%` | `+104.39%` | `-43.51%` | `-43.51%` |

### Per-Pair and Quarterly Breakdown (USDT)

| Breakdown | Training (`20240118–20250928`) | Validation (`20250928–20260422`) |
| --- | --- | --- |
| `ETH/USDT` | **`+36.32` USDT** (`22` trades, `36.4%` win; `52.9%` of positive pair gains) | `-9.81` USDT (`7` trades) |
| `BTC/USDT` | **`+32.30` USDT** (`29` trades, `41.4%` win; `47.1%` of positive pair gains) | `-11.97` USDT (`9` trades) |
| `SOL/USDT` | `-18.80` USDT (`25` trades, `32.0%` win) | `-4.04` USDT (`3` trades) |
| Quarters | `2024-Q1` `+47.85`, `2024-Q2` `-26.65`, `2024-Q3` `+12.37`, `2024-Q4` `+6.93`, `2025-Q1` `-5.71`, `2025-Q2` `+8.89`, `2025-Q3` `+6.12` (`5` of `7` quarters positive) | `2025-Q4` `-19.99` (Nov `0` trades flat in cash; Dec `-16.48` bear-rally head-fakes), `2026-Q1` `-10.69`, `2026-Q2` `+4.86` |

---

## 3. Cost Stress, `5m` Detail Replay, and Walk-Forward Diagnostics

### Fee Multipliers & Post-Processed Adverse Fill Stress

Because `H002` cut turnover by ~`80%`, it stayed solidly net-positive across `train` and `train + validation` combined even at **double fees (`0.20%`/side)** and **`+25 bps`/side** adverse fill movement:

| Scenario | Train net return | Validation net return | Combined `train + val` P&L |
| --- | ---: | ---: | ---: |
| Baseline (`0.10%` fee/side) | `+4.98%` (`+49.82` USDT) | `-2.58%` (`-25.82` USDT) | **`+24.00` USDT (`+2.40%`)** |
| `1.5×` fee (`0.15%` fee/side) | `+4.60%` (`+46.01` USDT) | `-2.68%` (`-26.76` USDT) | **`+19.25` USDT (`+1.93%`)** |
| `2.0×` fee (`0.20%` fee/side) | `+4.22%` (`+42.19` USDT) | `-2.77%` (`-27.69` USDT) | **`+14.51` USDT (`+1.45%`)** |
| `5m` detail intrabar replay (`0.10%` fee/side) | not re-run | `-2.58%` (`19` trades, identical) | — |
| Baseline + `5` bps/side adverse fill | `+4.60%` | `-2.68%` | **`+19.25` USDT** |
| Baseline + `10` bps/side adverse fill | `+4.22%` | `-2.77%` | **`+14.51` USDT** |
| Baseline + `25` bps/side adverse fill | `+3.08%` | `-3.05%` | **`+0.27` USDT** |
| Baseline + `50` bps/side adverse fill | `+1.17%` | `-3.52%` | `-23.47` USDT |

### Pre-Registered 91-Day Walk-Forward Slices (`walk-forward-1..7`)

Notice `walk-forward-3` (`20250116–20250417`, market `-35.09%`), where `H001` lost `-70.89 USDT` (`-7.09%`): `H002`'s regime filter cut that loss by **`90.8%`** down to `-6.55 USDT` (`-0.66%`), leaving net sum across all 7 forward slices slightly positive (`+0.72 USDT` vs `-90.78 USDT` on `H001`).

| Slice | UTC range | Trades | H002 Net P&L | H002 Return | Market | H002 Wallet DD | H001 Return (ref) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `walk-forward-1` | `20240718–20241017` | 10 | `+5.72` USDT | `+0.57%` | `-6.93%` | `1.21%` | `+0.77%` |
| `walk-forward-2` | `20241017–20250116` | 13 | `+12.60` USDT | `+1.26%` | `+37.73%` | `1.48%` | `+0.82%` |
| `walk-forward-3` | `20250116–20250417` | 9 | `-6.55` USDT | `-0.66%` | `-35.09%` | `2.46%` | `-7.09%` |
| `walk-forward-4` | `20250417–20250717` | 16 | `+21.84` USDT | `+2.18%` | `+61.79%` | `2.83%` | `+1.06%` |
| `walk-forward-5` | `20250717–20251016` | 15 | `-12.13` USDT | `-1.21%` | `+7.75%` | `2.51%` | `-0.37%` |
| `walk-forward-6` | `20251016–20260115` | 10 | `-14.29` USDT | `-1.43%` | `-17.44%` | `2.28%` | `-1.94%` |
| `walk-forward-7` | `20260115–20260416` | 7 | `-6.46` USDT | `-0.65%` | `-31.21%` | `1.45%` | `-2.33%` |

---

## 4. Bias & Startup Verification

- **Lookahead analysis:** Passed with **`has_bias=False`, `0` biased entry signals, `0` biased exit signals, `0` biased indicators** on both `validation` (`20261116T095615220128`, `20` signals checked) and `bias-dev` (`20261116T095624083782`, `20` signals checked across `20240118–20260422`).
- **Recursive & indicator lookahead analysis:** Executed on `BTC/USDT` (`20261116T095632217140`), `ETH/USDT` (`20261116T095636566905`), and `SOL/USDT` (`20261116T095640921035`) across startup lengths `50, 100, 200, 240, 400`. Expected `nan%` appeared below the `224`-bar indicator horizon (`50, 100, 200`) and **`0.000%` drift** at `240` (strategy setting) and `400`, with zero indicator lookahead.

---

## 5. Strict Gate Audit & Why the Holdout Stays Sealed

Comparing `H002` strictly against the pre-registered criteria in [H002-preregistration.md](H002-preregistration.md) without post-hoc relaxation:

| Pre-Registered Gate | Requirement | Observed H002 Result | Verdict |
| --- | --- | --- | --- |
| Technical & bias gate | `0` lookahead bias; `0.000%` recursive drift at `>=240`; deterministic `5m` detail match | `0` biased signals; `0.000%` drift at `240/400`; `5m` detail matched `-25.82 USDT` | **PASS** |
| Sample coverage | `train >= 25` and `val >= 8` (combined `>= 35`) | `train = 76`, `val = 19`, `combined = 95` | **PASS** |
| Train expectancy & return | Net return `> 0` and expectancy `> 0` at `0.10%` fee | `+4.98%` (`+49.82 USDT`), expectancy `+0.656 USDT/trade`, PF `1.44` | **PASS** |
| Max account drawdown | `<= 8.0%` in both `train` and `validation` | `2.82%` realized (`4.14%` wallet) train; `3.14%` realized (`3.94%` wallet) val | **PASS** |
| Combined cost resilience | Combined `train + val` net return `> 0` at `1.5×` fee and `+10 bps`/side adverse fill | `+19.25 USDT` at `1.5×` fee; `+14.51 USDT` at `+10 bps`/side | **PASS** |
| Pair concentration | Top pair `<= 85%` of positive gains | `ETH` `52.9%` (`+36.32`), `BTC` `47.1%` (`+32.30`); `SOL` lost `-1.88%` in train | **PASS** |
| **Validation bear-regime loss cap** | Validation expectancy `>= 0` **OR** validation loss no worse than **`-2.00%`** (`-20.00 USDT`) | Validation return **`-2.58%` (`-25.82 USDT`)** (`-2.68%` at `1.5×` fee), missed cap by `0.58%` (`5.82 USDT`) | **FAIL** |

### Disposition & Structural Diagnosis for `H003`
1. **Do NOT relax the `-2.00%` gate:** `H002` improved `train + validation` P&L by **`+97.54 USDT`** over `H001` (`-73.54 USDT -> +24.00 USDT`), halved wallet drawdown (`8.71% -> 4.14%`), and stayed profitable across `train + validation` even under `2×` fees. However, during the `-43.51%` validation bear market (`2025-12` and `2026-03`), `19` short-lived `200h` (~8.3-day) counter-trend bounces briefly lifted `SMA200` slope positive and triggered false breakouts (`-25.82 USDT`), breaching the pre-registered `-2.00%` bear-window loss cap by `5.82 USDT`.
2. **Untouched holdout (`20260422–20261114`) remains SEALED:** Zero `untouched-*` runs exist. Preserving the one-shot holdout rule prevents data snooping.
3. **Actionable engineering & research outcome:**
   - `PersonalSpotBreakout` (`--strategy PersonalSpotBreakout` or guarded `--strategy PersonalSpotBreakoutGuarded`) is now available as a dramatically cleaner, lower-churn **paper-trading candidate** than `H001`.
   - If pursuing a live-eligible hypothesis **`H003`**, the diagnostic points to one specific structural gap: a `200h` (`8.3`-day) moving average is still fast enough to turn upward during multi-day bear-market dead-cat bounces (`2025-12`), whereas a multi-week macro trend filter (e.g., `720h` / 30-day regime or market-breadth confirmation requiring `BTC/USDT` macro uptrend before altcoin entries) directly targets those `19` bear-window head-fakes before opening the sealed holdout.
