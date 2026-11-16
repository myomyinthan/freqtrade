# Milestone 3 Paper Operations Smoke & Drills Report

Prepared: `2026-11-16`  
Status: **B14 Smoke PASSED · B15 Local Monitoring/Alerts PASSED · B16 Operational Drills PASSED · B17 30-Day Observation Pending**

> **Safety & Risk Label:** `PersonalSpotBaseline` (`H001`) failed historical economic screening (`bot/docs/research/H001-binance-usdt-spot-report.md`) and is operated here **strictly as a credential-free dry-run engineering fixture**. **External daily-loss guard enforcement (`M4`) is not yet integrated; no daily loss ceiling is claimed.**

## 1. B14 — Credential-Free Local Paper Smoke

Launched via `python3 bot/scripts/preflight.py run bot/configs/pilot.local.json --strategy PersonalSpotBaseline --local-api` against the pinned `freqtrade:2026.10` (`linux/arm64`) image (`sha256:1bb9a6b11a4dae39444331aa324b139dcd635f6a1c586ce9ecccac17994edc0c`).

| Check | Verified evidence |
| --- | --- |
| Credentials & host ports | Zero exchange API keys in `pilot.local.json`; zero host port mappings in `bot/compose.yaml`. |
| Resolved runtime config (`verify-api`) | `dry_run=true`, `trading_mode="spot"`, `force_entry_enable=false`, `strategy="PersonalSpotBaseline"`, `exchange="binance"`, `stake_currency="USDT"`, `stake_amount="50"`, `max_open_trades=2`. |
| Dedicated paper ledger | `sqlite:////freqtrade/bot/runtime/paper/baseline.paper.sqlite` (`94,208` bytes, isolated from `trades.paper.sqlite` and any live DB). |
| Local API authentication | Bound strictly to `127.0.0.1:8080` inside the container namespace; unauthenticated `GET /api/v1/show_config` returned `HTTP 401`; Basic-authenticated probe with `0600` `api.auth.json` returned `HTTP 200`. |
| Spot pairlist & candle freshness | `BTC/USDT`, `ETH/USDT`, and `SOL/USDT` loaded `1h` spot candles up to `2026-11-16 07:00:00+00:00` (`completed_candle_age_seconds = 2814.07s`, well inside the `7200s` two-interval freshness bound). |
| Protections loaded | `CooldownPeriod` (1 candle) and global `StoplossGuard` (2 stoplosses in 24 candles) active at startup. |

## 2. B15 — Status Reporting, Local Alerts, Log Rotation, and Sanitized Export

- **Rotating paper log:** `preflight.py` passes `--logfile /freqtrade/bot/runtime/paper/logs/freqtrade.paper.log`, activating Freqtrade's `RotatingFileHandler` (`10 MiB × 10` files).
- **Local alert rules (`paper_status.py status`):** Evaluates `failed_heartbeat` (`>120s`), `stale_feed` (`>7200s` completed candle age or empty dataprovider), `repeated_errors` (`>=3` `ERROR`/`CRITICAL` lines in tail window), `disk_pressure` (`<1 GiB` free), and `restart_detected` (non-zero container exit, Docker `RestartCount > 0`, or missing clean-shutdown marker).
- **External notifications:** Explicitly disabled (`disabled_requires_user_authorized_destination`) until an alert destination is chosen.
- **Sanitized export:** `paper_status.py export` generated `0600` `m3-sanitized-export.json` with passwords, JWT/WS tokens, API keys, and `Authorization` headers redacted (`[REDACTED]`).

## 3. B16 — Incident, Pause, Duplicate-Writer, Backup, and Isolated Restore Drills

| Drill | Action executed | Observed outcome |
| --- | --- | --- |
| **Duplicate writer block** | Ran a second `preflight.py run` while `personalspot-paper-runner` was active. | Rejected immediately with exit code `2` (`another paper runner already holds runner.lock; duplicate writers are forbidden`) before touching Compose or SQLite. |
| **Pause vs. stop distinction & entry reconciliation** | Executed `paper_status.py pause`, waited across a worker heartbeat, then `paper_status.py resume`. | Bot transitioned `RUNNING -> PAUSED` (`last_heartbeat_state="PAUSED"`, `exit_supervision_active=true`, zero remaining open `buy` entry orders) while keeping the container and exit loop alive, then resumed `PAUSED -> RUNNING`. Unit fixture verified `buy` entries cancel/reload while protective `sell` orders remain untouched. |
| **Network outage & recovery** | Disconnected `personalspot-paper-runner` from `personalspot-paper_default` for `12s`, inspected status/logs, and reconnected. | CCXT WebSocket watches logged 3 `NetworkError` disconnects (`BTC/USDT`, `ETH/USDT`, `SOL/USDT`), triggering the `repeated_errors` alert in `paper_status.py`. After reconnecting, `verify-api` confirmed automatic recovery (`last_process_ts` advancing, fresh candles, zero crashed processes). |
| **Online SQLite backup & isolated restore** | Ran `paper_status.py backup`, `verify-backup`, and `restore-drill` into `/tmp/personalspot-m3-restore-check`. | Online backup passed `PRAGMA quick_check`; isolated restore passed `PRAGMA integrity_check="ok"` with all 6 Freqtrade tables (`KeyValueStore`, `orders`, `pairlocks`, `trade_custom_data`, `trades`, `wallet_history`), and live `baseline.paper.sqlite` SHA-256 (`b3c2a344...ea55d1`) was unchanged. |
| **Controlled stop & paused restart** | Stopped container cleanly (`docker stop`), inspected offline SQLite ledger, and relaunched with `--state paused --local-api`. | Clean shutdown logged; offline read-only inspection succeeded even with Docker Desktop's virtiofs `-shm` absent; second launch manifest recorded (`launch_manifest_count=2`) and bot booted directly into `PAUSED` state preserving the existing SQLite ledger. |

## 4. Remaining Boundary (`B17` and beyond)

- **B17 (Long-window paper pilot):** Active on `PersonalSpotMacroBreakoutGuarded` (`H003`). Requires continuous uptime (`30` calendar days and `30` natural trades proposed; laptop sleep invalidates continuous-uptime claims). Track progress with `bot/scripts/pilot_audit.py`; move to the `bot/deploy/systemd/` bundle on an always-on host before claiming the continuous window.
- **B20 packaging:** Credential-free user `systemd` units and recovery procedures live under `bot/deploy/systemd/` and `docs/operations/M4-guard-and-deployment-guide.md`. Host install is optional until continuous-uptime evidence is required.
- **B21 / live boundary:** Still blocked pending `B17` observation completion and separate explicit capital/account authorization.
