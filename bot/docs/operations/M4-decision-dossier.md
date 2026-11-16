# Live-Authorization Boundary Decision Dossier (`B21`)

Prepared: `2026-11-16`  
Engineering Deliverable Status: **M0–M4 Research, Paper Runner, Monitoring & Persisted Guard Infrastructure COMPLETE (`29/29` container tests passing)**  
Live Trading Recommendation: **DO NOT ENABLE LIVE TRADING (`H001` failed economic validation; system stops at the live authorization boundary)**

---

## 1. Executive Summary

All planned engineering milestones (`M0` through `M4`) are implemented, tested inside the pinned `freqtrade:2026.10` (`sha256:1bb9a6b11a4dae39444331aa324b139dcd635f6a1c586ce9ecccac17994edc0c`) runtime, and verified through credential-free paper drills:

- **Owned fork & reproducible pins (`M0`):** `origin` (`myomyinthan/freqtrade`) separated from `upstream` (`freqtrade/freqtrade`) on release `2026.10` (`4cf0351e08d26e96a6429ef48103b726bb230cf8`), zero upstream engine edits, offline CI workflow (`.github/workflows/personal-spot.yml`), secrets/runtime git-ignored.
- **Audited market data & unbiased evaluation (`M1`–`M2`):** `25,152` requested `1h` candles and `301,824` `5m` candles per pair (`BTC/USDT`, `ETH/USDT`, `SOL/USDT`, `20240101–20261114`) audited gap-free and frozen by SHA-256 (`be44e132bb55…`). Lookahead (`20/169` validation signals) and recursive startup checks (`50/100/200/400` candles) passed.
- **Economic outcomes (`H001` -> `H002` -> `H003`):**
  - `H001` (`PersonalSpotBaseline`, `1h` SMA20/50) lost `-2.26%` in training and `-5.09%` in validation (`-73.54 USDT` combined).
  - `H002` (`PersonalSpotBreakout`, `7d/3d` Donchian + `SMA200`) swung `train + validation` positive (`+24.00 USDT` / `+2.40%`), missing its `-2.00%` bear-window cap (`-2.58%`).
  - `H003` (`PersonalSpotMacroBreakout`, `14d/4d` Donchian + `SMA120/SMA360` macro stack) achieved **`+7.76%` in training** (profit factor `2.36`, daily Sharpe `1.38`, wallet DD `2.80%`) and **`+5.42%` (`+54.22 USDT`) across `train + validation`** (positive on all 3 pairs and surviving `2×` fees and `+50 bps`/side slippage), while posting `-2.34%` (`3.23%` wallet DD) during the `-43.51%` validation bear crash — `0.34%` (`3.40 USDT`) shy of its strict `-2.00%` bear-window cap (`bot/docs/research/H003-binance-usdt-spot-report.md`).
  - To prevent validation curve-fitting, further tuning stopped at `H003` and the **untouched holdout (`20260422–20261114`) remains 100% sealed**, awaiting an explicit user decision on whether to freeze `H003` (`PersonalSpotMacroBreakoutGuarded`) for the one-shot holdout test and 30-day paper pilot.
- **Paper operations & persisted daily entry-halt guard (`M3`–`M4`):** Single-writer locking, rotating logs, sanitized exports, local alerts, online SQLite backup + isolated restore, `PersonalSpotGuarded` fail-closed `confirm_trade_entry` (`BaseException -> False`), and separate `guard_runner.py` polling/pause/entry-only-cancellation service (`5.9–18.5 ms` poll, `0.94–1.13s` container API pause + reconciliation) are all verified.

Because **engineering readiness does not substitute for positive economic expectancy**, the project stays in **research / dry-run mode**.

---

## 2. Verified Component & Evidence Matrix

| Area | Artifact | Result |
| --- | --- | --- |
| Engine & version lock | `bot/VERSION.lock.json`, `bot/compose.yaml` | Pinned `2026.10` (`linux/arm64`), read-only overlay mounts, zero host ports |
| Venue capability review | `bot/docs/venues/binance-usdt-spot.md` | `BTC/USDT`, `ETH/USDT`, `SOL/USDT` `TRADING`, `5 USDT` min notional, `0.10%` provisional regular-user fee |
| Historical evaluation | `bot/docs/research/H001-binance-usdt-spot-report.md` | Technical **PASS**, Economic **FAIL**; `20260422–20261114` holdout **SEALED** |
| Paper smoke & incident drills | `bot/docs/operations/M3-paper-smoke-and-drills.md` | Duplicate-writer reject, pause/resume, network outage alert + recovery, online backup + isolated restore **PASSED** |
| Persisted daily entry-halt guard | `bot/risk/guard.py`, `bot/scripts/guard_runner.py`, `bot/strategies/PersonalSpotGuarded.py`, `bot/docs/operations/M4-guard-and-deployment-guide.md` | Normalized ledger/fill/flow equity, fail-closed `strategy_safe_wrapper` integration test, live `heartbeat_gap` & `operator_halt` drills + latched restart rejection **PASSED** |
| Automated test suite | `bot/tests/test_*.py` (`29` tests) | `29 / 29` passed inside pinned container with `--network none` |

---

## 3. Residual Risks & Venue Limitations

1. **Negative strategy expectancy (`H001`):** Deploying `H001` with real capital would be expected to lose money to whipsaws and fee drag. A new pre-registered hypothesis (`H002`) must pass training, validation, cost stress, and the sealed holdout (`20260422–20261114`) first, followed by the `B17` 30-day / 30-trade natural paper observation window.
2. **Polling guard is not a hard loss cap:** `guard_runner.py` halts *new* entries within `~10s` (or `<=30s` lease expiry if the guard daemon dies) and cancels open `buy` orders, while open spot holdings remain exposed to adverse price gaps, exchange outages, or off-exchange stoploss delays.
3. **Simulated fills vs. live book microstructure:** Candle backtests and dry-run order-book top-1 fills do not prove queue priority, partial-fill dust handling, API rate-limit throttling under volatility, or exchange maintenance behavior.
4. **Unverified operator jurisdiction & fee tier:** Public `api.binance.com` market data succeeded without credentials; personal Binance account eligibility, KYC/jurisdiction compliance, IP-restricted spot-only API keys (withdrawals disabled), and actual maker/taker fee tier remain unverified.
5. **Local laptop sleep:** Continuous 24/7 operation cannot be claimed on a sleeping laptop; an always-on host requires an explicit hosting & budget decision.

---

## 4. Required User Decisions Before Any Future Live Consideration

No live configuration, API key prompt, or live launch command exists in this repository. Even **after** a future strategy hypothesis (`H002`) passes historical validation and a 30-day continuous dry-run pilot, explicit user authorization is still required on all of the following:

1. **Economic candidate:** Approval of a validated strategy dossier with positive stressed expectancy and unconsumed-holdout confirmation.
2. **Venue & account eligibility:** Confirmed exchange/subaccount legal in your jurisdiction, with dedicated **spot-only, withdrawal-disabled** API credentials.
3. **Hard risk & capital numbers:** Maximum total allocated quote capital, fixed per-order stake, max concurrent positions (`<=2`), daily entry-halt loss limit (quote & `%`), and lifetime stop/rollback drawdown ceiling.
4. **Hosting & alert destination:** Always-on single-host budget (or local-only acceptance) and an authorized notification channel for guard latches, stale feeds, and heartbeat failures.
5. **Rollback & incident ownership:** Operator response SLA when open spot positions remain exposed during a guard halt, exchange outage, or credential rotation.
