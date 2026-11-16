# Milestone 4 — Single-Host Paper Deployment & Recovery Guide (`B20`)

Prepared: `2026-11-16`  
Scope: **Credential-free dry-run deployment only** (no paid cloud host provisioned, no live trading profile or API keys included).

## 1. Reproducible Single-Host Bundle

| Component | Exact reference / path |
| --- | --- |
| Fork & upstream commit | Release `2026.10`, commit `4cf0351e08d26e96a6429ef48103b726bb230cf8` (`bot/VERSION.lock.json`) |
| Immutable runtime image | `docker.io/freqtradeorg/freqtrade@sha256:1bb9a6b11a4dae39444331aa324b139dcd635f6a1c586ce9ecccac17994edc0c` (`linux/arm64`; update `VERSION.lock.json` and `compose.yaml` together after verifying the `linux/amd64` digest if moving to an x86_64 Linux host) |
| Compose manifest | `bot/compose.yaml` — read-only bind mounts for `configs/base.example.json`, `risk/`, `scripts/`, and `strategies/`; writable `0700` `runtime/paper/` mount; **zero host ports exposed** |
| Paper launcher | `bot/scripts/preflight.py` — enforces `dry_run=true`, `trading_mode=spot`, `force_entry_enable=false`, single-writer `runner.lock`, `0600` `api.auth.json`, and armed guard verification |
| Separate guard service | `bot/scripts/guard_runner.py` + `bot/risk/guard.py` — atomic `0600` `guard.state.json` persistence, 10s polling target, 30s entry-permission lease, container-loopback `/api/v1/pause` + pending-`buy` cancellation |
| Guarded strategy | `bot/strategies/PersonalSpotGuarded.py` — wraps `PersonalSpotBaseline` (`H001`) with a fail-closed `confirm_trade_entry` callback that catches `BaseException` and returns `False` so exceptions never escape into Freqtrade's `strategy_safe_wrapper(default_retval=True)` |

## 2. Measured Guard Timing & Enforcement Bounds (`2026-11-16` Drill)

> **Important risk boundary:** A polling guard halts **new entries** and cancels unfilled **entry** orders while preserving normal exits and protective sells. It is **not** a guaranteed monetary loss ceiling: open spot positions remain exposed to market moves, price gaps, and order-submission races until Strategy exit or stoploss fills.

| Stage | Configured / Measured Value |
| --- | --- |
| Poll interval (`poll_interval_seconds`) | `10.0s` target |
| Local entry lease (`max_age_seconds`) | `30.0s` hard expiry (if `guard_runner.py` crashes or stalls, `PersonalSpotGuarded.confirm_trade_entry` automatically denies entries after `<= 30s`) |
| Steady-state SQLite + state poll latency | `5.89 ms – 18.51 ms` measured locally |
| End-to-end API halt + pending-entry reconciliation latency | `937.86 ms – 1,125.97 ms` measured via `docker exec` loopback HTTP to `127.0.0.1:8080` (`POST /api/v1/pause`, `GET /api/v1/status`, readback verification) |
| Worst-case detection-to-local-gate bound | `~10.02s` on poll breach (`poll_interval + poll_latency`), or `<= 30.0s` on total guard daemon death |
| Restart persistence | Verified: stopping `personalspot-paper-runner` while latched (`operator_halt:m4_operator_halt_drill`) and re-running `preflight.py run --strategy PersonalSpotGuarded --local-api` failed closed with exit code `2` |

## 3. Startup Sequence (Two Processes: Guard + Paper Runner)

Run from the `freqtrade/` repository root:

```sh
settings=bot/configs/pilot.local.json

# 1. Initialize guard policy (25 USDT daily entry-halt fixture, 30s lease, 10s poll)
python3 bot/scripts/guard_runner.py init "$settings" \
  --max-loss-quote 25 --max-age-seconds 30 --poll-interval-seconds 10

# 2. If starting mid-UTC-day on a reconciled ledger, explicitly register opening equity
python3 bot/scripts/guard_runner.py bootstrap-day "$settings" \
  --reason "initial UTC day paper baseline registration"

# 3. Terminal / systemd unit 1: start the separate guard polling daemon immediately
python3 bot/scripts/guard_runner.py watch "$settings"

# 4. Terminal / systemd unit 2 (within 30s lease): launch the guarded dry-run container
python3 bot/scripts/preflight.py run "$settings" --strategy PersonalSpotGuarded --local-api
```

## 4. Incident & Recovery Procedures

### A. Guard Latch (`daily_loss`, `heartbeat_gap`, `missing_utc_opening_equity`, or `operator_halt`)
1. Inspect combined container, ledger, and guard state:
   ```sh
   python3 bot/scripts/paper_status.py status
   python3 bot/scripts/guard_runner.py status bot/configs/pilot.local.json
   ```
2. Verify `enforcement_pending` is `false` and `order_sides.pending_entry_orders` is `0`. Protective `sell` orders and normal strategy exits continue while `state="paused"`.
3. Note that **UTC midnight rollover or container restart will NOT clear a prior breach**.
4. Only after reconciling equity, confirming daily loss is below `max_loss_quote` (or registering a new UTC day's reconciled baseline), and confirming `guard_runner.py watch` is pulsing fresh snapshots:
   ```sh
   python3 bot/scripts/guard_runner.py rearm bot/configs/pilot.local.json \
     --reason "operator verified reconciled paper ledger and fresh feed"
   python3 bot/scripts/paper_status.py resume
   ```

### B. Consistent Backup & Isolated Restore Verification
1. Create an online SQLite snapshot and archive aligned copies of `guard.policy.json`, `guard.state.json`, and `m4-sanitized-export.json` (`0600` permissions; Proposed retention: 7 daily + 4 weekly snapshots):
   ```sh
   python3 bot/scripts/paper_status.py backup bot/runtime/paper/daily.backup.sqlite
   python3 bot/scripts/paper_status.py export bot/runtime/paper/daily.export.json
   ```
2. Test restore **outside** `bot/runtime/paper/` before relying on any backup:
   ```sh
   python3 bot/scripts/paper_status.py restore-drill \
     bot/runtime/paper/daily.backup.sqlite /tmp/isolated-paper-restore
   rm -rf /tmp/isolated-paper-restore
   ```
3. Never overwrite `baseline.paper.sqlite` while `personalspot-paper-runner` is active, and never delete rows from `trades` or `orders` to force a clean reconciliation.
