# Live-Authorization Boundary Decision Dossier (`B21`)

Prepared: `2026-11-16`  
Engineering Deliverable Status: **M0–M4 Research, One-Shot Holdout (`H003` PASSED), Paper Runner, Monitoring, Persisted Guard, `B17` Continuity Audit & `B20` Systemd Bundle COMPLETE (`43/43` container tests passing)**  
Current Operating State: **Monitored Dry-Run Paper Pilot Active (`PersonalSpotMacroBreakoutGuarded` + `guard_runner.py`); Live Trading Still Requires Separate Explicit Capital/Account Authorization After Paper Observation (`B17`)**

---

## 1. Executive Summary

All planned engineering milestones (`M0` through `M4`) are implemented, tested inside the pinned `freqtrade:2026.10` (`sha256:1bb9a6b11a4dae39444331aa324b139dcd635f6a1c586ce9ecccac17994edc0c`) runtime, and verified through credential-free paper drills:

- **Owned fork & reproducible pins (`M0`):** `origin` (`myomyinthan/freqtrade`) separated from `upstream` (`freqtrade/freqtrade`) on release `2026.10` (`4cf0351e08d26e96a6429ef48103b726bb230cf8`), zero upstream engine edits, offline CI workflow (`.github/workflows/personal-spot.yml`), secrets/runtime git-ignored.
- **Audited market data & unbiased evaluation (`M1`–`M2`):** `25,152` requested `1h` candles and `301,824` `5m` candles per pair (`BTC/USDT`, `ETH/USDT`, `SOL/USDT`, `20240101–20261114`) audited gap-free and frozen by SHA-256 (`be44e132bb55…`). Lookahead (`20/169` validation signals) and recursive startup checks (`50/100/200/400` candles) passed.
- **Economic outcomes (`H001` -> `H002` -> `H003`):**
  - `H001` (`PersonalSpotBaseline`, `1h` SMA20/50) lost `-2.26%` in training and `-5.09%` in validation (`-73.54 USDT` combined).
  - `H002` (`PersonalSpotBreakout`, `7d/3d` Donchian + `SMA200`) swung `train + validation` positive (`+24.00 USDT` / `+2.40%`), missing its `-2.00%` bear-window cap (`-2.58%`).
  - `H003` (`PersonalSpotMacroBreakout`, `14d/4d` Donchian + `SMA120/SMA360` macro stack) achieved **`+7.76%` in training** (profit factor `2.36`, daily Sharpe `1.38`, wallet DD `2.80%`), **`-2.34%` in the `-43.51%` validation crash** (`3.23%` wallet DD), and — after user authorization to freeze `H003` and execute the one-shot holdout (`untouched-be44e132bb55-20260422-20261114`) — **PASSED the untouched out-of-sample test (`20260422–20261114`) with `+1.76%` (`+17.62 USDT`) vs `-12.41%` buy-and-hold, profit factor `3.90`, daily Sharpe `1.22`, and `1.28%` wallet drawdown** (`0.34%` realized DD, `+1.21%` even after `+50 bps`/side adverse fill stress; full `1,031`-day cumulative net gain `+71.84 USDT` across `71` trades with all 3 pairs net positive: `ETH +36.29`, `BTC +18.03`, `SOL +17.52` USDT; `bot/docs/research/H003-binance-usdt-spot-report.md`).
  - The `20260422–20261114` holdout is now **consumed** (`research.py` verified blocking any second run), and `PersonalSpotMacroBreakoutGuarded` advances into the **monitored dry-run paper pilot (`B17`)**.
- **Paper operations & persisted daily entry-halt guard (`M3`–`M4`):** Single-writer locking, rotating logs, sanitized exports, local alerts, online SQLite backup + isolated restore, guarded fail-closed `confirm_trade_entry` (`BaseException -> False`), and separate `guard_runner.py` polling/pause/entry-only-cancellation service (`5.9–18.5 ms` poll, `0.94–1.13s` container API pause + reconciliation) are all verified.
- **`B17` continuity audit & `B20` packaging:** `bot/scripts/pilot_audit.py` tracks heartbeat gaps, natural-trade progress, and fill/fee drift; credential-free user `systemd` units live under `bot/deploy/systemd/` for optional always-on hosts (laptop sleep still invalidates continuous-uptime claims until installed there).

Because **engineering readiness does not substitute for positive economic expectancy**, the project stays in **research / dry-run mode**.

---

## 2. Verified Component & Evidence Matrix

| Area | Artifact | Result |
| --- | --- | --- |
| Engine & version lock | `bot/VERSION.lock.json`, `bot/compose.yaml` | Active pin `2026.10` `linux/arm64`. `linux/amd64` digest recorded and offline-tested; no host provisioned |
| Venue capability review | `bot/docs/venues/binance-usdt-spot.md` | `BTC/USDT`, `ETH/USDT`, `SOL/USDT` `TRADING`, `5 USDT` min notional, `0.10%` provisional regular-user fee |
| Historical evaluation | `bot/docs/research/H001-…`, `H002-…`, `H003-binance-usdt-spot-report.md` | `H001` FAIL; `H002` +2.40% dev; **`H003` PASSED untouched holdout (`+1.76%` vs `-12.41%` mkt, PF `3.90`, `1.28%` wallet DD; holdout now consumed)** |
| Automated test suite | `bot/tests/test_*.py` (`43` tests) | `43 / 43` passed inside pinned container with `--network none` |
| B17 continuity audit | `bot/scripts/pilot_audit.py` | Live pilot reports `observing_in_progress` (cash regime; `0` natural trades yet; no uptime gaps while running) |
| B20 host bundle | `bot/deploy/systemd/`, `bot/scripts/host_ready.py` | No always-on host exists. Readiness verdict on this Mac is `not_an_always_on_host`; systemd units remain uninstalled |

---

## 3. Residual Risks & Venue Limitations

1. **Selective sample size & holdout consumption (`H003`):** While `H003` was profitable across `train` (`+7.76%`, `45` trades), full `train + val` (`+5.42%`, `60` trades), and the untouched holdout (`+1.76%`, `11` trades during a `-12.41%` market decline; `+7.18%` / `+71.84 USDT` across all `1,031` days on `100 USDT` max slot exposure), `11` holdout trades over `206` days is a low-frequency sample (`p = 0.2737`) on a present-day 3-pair universe with survivorship bias. Complete the `B17` monitored paper pilot (`30` days / `30` natural trades, extended if trades are sparse) before considering real capital.
2. **Polling guard is not a hard loss cap:** `guard_runner.py` halts *new* entries within `~10s` (or `<=30s` lease expiry if the guard daemon dies) and cancels open `buy` orders, while open spot holdings remain exposed to adverse price gaps, exchange outages, or off-exchange stoploss delays.
3. **Simulated fills vs. live book microstructure:** Candle backtests and dry-run order-book top-1 fills do not prove queue priority, partial-fill dust handling, API rate-limit throttling under volatility, or exchange maintenance behavior.
4. **Unverified operator jurisdiction & fee tier:** Public `api.binance.com` market data succeeded without credentials; personal Binance account eligibility, KYC/jurisdiction compliance, IP-restricted spot-only API keys (withdrawals disabled), and actual maker/taker fee tier remain unverified.
5. **Local laptop sleep:** Continuous 24/7 operation cannot be claimed on a sleeping laptop. `launchd` cannot read this checkout under `Documents` without Full Disk Access, so awake-session supervision uses `host_supervise.py session`, including `caffeinate -s` while on AC power with the lid open. A closed lid still sleeps. An always-on host still requires an explicit hosting and budget decision before the `B17` window can be treated as continuous.

---

## 4. Required User Decisions Before Any Future Live Consideration

No live configuration, API key prompt, or live launch command exists in this repository. Even **after** a future strategy hypothesis (`H002`) passes historical validation and a 30-day continuous dry-run pilot, explicit user authorization is still required on all of the following:

1. **Economic candidate:** Approval of a validated strategy dossier with positive stressed expectancy and unconsumed-holdout confirmation.
2. **Venue & account eligibility:** Confirmed exchange/subaccount legal in your jurisdiction, with dedicated **spot-only, withdrawal-disabled** API credentials.
3. **Hard risk & capital numbers:** Maximum total allocated quote capital, fixed per-order stake, max concurrent positions (`<=2`), daily entry-halt loss limit (quote & `%`), and lifetime stop/rollback drawdown ceiling.
4. **Hosting & alert destination:** Always-on single-host budget (or local-only acceptance) and an authorized notification channel for guard latches, stale feeds, and heartbeat failures.
5. **Rollback & incident ownership:** Operator response SLA when open spot positions remain exposed during a guard halt, exchange outage, or credential rotation.
