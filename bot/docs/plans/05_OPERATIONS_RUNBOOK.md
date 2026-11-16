# Operation, deployment and recovery runbooks

This file describes future commands and procedures. No runtime, exchange, approved capital or deployment currently exists. Commands are templates for Sol to verify against the selected release; unresolved variables are intentional. Do not copy a template into a real trading session without the corresponding preflight.

## 1. Runtime readiness

Read [LOCAL_READINESS.md](LOCAL_READINESS.md) first. Recheck GitHub network/authentication, Docker daemon, Compose availability and runtime architecture. The observed default Python 3.9 does not satisfy the inspected stable Python requirement; use the selected supported runtime and do not mutate system Python. Docker being installed does not prove its daemon or Compose plugin works.

Before using a downloaded image, verify repository/tag provenance, immutable digest and supported platform. Record the actual engine version. The Compose service named `freqtrade` below is a proposed project service with the image entrypoint preserved, read-only `bot/` sources and writable runtime/data mounts. Sol must create and validate it first.

```sh
# Run from the verified fork root, after Compose and the daemon are operational.
docker compose version
docker info
docker compose -p personalspot-paper -f bot/compose.yaml config --quiet
docker compose -p personalspot-paper -f bot/compose.yaml run --rm freqtrade --version
docker compose -p personalspot-paper -f bot/compose.yaml run --rm freqtrade backtesting --help
docker compose -p personalspot-paper -f bot/compose.yaml run --rm freqtrade lookahead-analysis --help
docker compose -p personalspot-paper -f bot/compose.yaml run --rm freqtrade recursive-analysis --help
```

Avoid printing rendered Compose configuration if it interpolates secrets. Version output must match the source release and image digest in `VERSION.lock.json`. Validate names/flags again after upgrades.

## 2. Historical research command templates

The implementation wrapper must create a unique run directory, resolve every variable from the frozen protocol, reject placeholders, and save command/config/data hashes. No credentials are needed for public data unless the chosen venue specifically requires read access. Populate an ignored runtime research config from tracked examples only after exchange/quote/pairs are known.

```sh
# Helper assumes the authored Compose service uses the Freqtrade entrypoint.
ft() {
  docker compose -p personalspot-paper -f bot/compose.yaml run --rm freqtrade "$@"
}

# BOT_RESEARCH_CONFIG is a container path to the resolved research config.
# BOT_DATASET_CONTAINER is the container path for this frozen dataset.
# BOT_DOWNLOAD_RANGE includes warmup before the evaluation window.
# BOT_EVAL_RANGE is one closed UTC range, e.g. YYYYMMDD-YYYYMMDD.
# BOT_FEE_PER_SIDE is a verified fractional fee; BOT_ONE_PAIR is one approved pair.
ft download-data -c "$BOT_RESEARCH_CONFIG" \
  --datadir "$BOT_DATASET_CONTAINER" \
  --timeframes 1h 5m --timerange "$BOT_DOWNLOAD_RANGE"

ft backtesting -c "$BOT_RESEARCH_CONFIG" \
  --userdir /freqtrade/bot/runtime/research \
  --strategy-path /freqtrade/bot/strategies -s PersonalSpotBaseline \
  --datadir "$BOT_DATASET_CONTAINER" --timerange "$BOT_EVAL_RANGE" \
  --timeframe 1h --fee "$BOT_FEE_PER_SIDE" \
  --enable-protections --cache none --export trades

# Repeat a manifested comparison run with --timeframe-detail 5m if data covers it.
ft lookahead-analysis -c "$BOT_RESEARCH_CONFIG" \
  --userdir /freqtrade/bot/runtime/research \
  --strategy-path /freqtrade/bot/strategies -s PersonalSpotBaseline \
  --datadir "$BOT_DATASET_CONTAINER" --timerange "$BOT_BIAS_RANGE"

ft recursive-analysis -c "$BOT_RESEARCH_CONFIG" \
  --userdir /freqtrade/bot/runtime/research \
  --strategy-path /freqtrade/bot/strategies -s PersonalSpotBaseline \
  --datadir "$BOT_DATASET_CONTAINER" --timerange "$BOT_RECURSIVE_RANGE" \
  -p "$BOT_ONE_PAIR" --startup-candle 50 100 200 400
```

Set a unique result path using the pinned version's supported output flag or capture the generated artifact path and copy it into the run directory. Never overwrite evidence or silently use a cached result. Archive raw tool output, including analysis cancellations and warnings. The bias and recursive ranges should satisfy their tool requirements and cover relevant signals; they are not automatically the same range as the economic test.

## 3. Starting a paper pilot

1. Resolve exchange, quote, pairs, paper-wallet size and fee assumptions; finish data/strategy checks. Verify the laptop/host can remain awake if claiming continuous operation.
2. Prepare a new dedicated paper DB and guarded runtime permissions. Never reuse a historical live DB or clear an existing DB to hide errors. Record a run ID, configuration hash and source/image versions.
3. Run the project's preflight against the same effective config/environment used by the trader. It must reject `dry_run=false`, non-spot mode, live credentials by default, force-entry, invalid stake, shared DB, stale guard state when guard enforcement is enabled, and unresolved values.
4. Start through the tested paper launcher. Verify the resolved mode from startup/status, correct strategy/pairs/wallet, candle freshness and authenticated local API if enabled. Confirm no live orders exist and the DB is the paper DB.
5. Observe normal entry, exit and stop paths. Do not force trades to satisfy counts; use synthetic fixtures for rare failure paths. Document paper fill assumptions and deviations from the historical model.

The early paper smoke may run before the external guard exists, clearly labeled **guard not implemented; no daily loss enforcement claimed**. The full readiness pilot must repeat relevant tests with the guard enabled before any live proposal.

## 4. Monitoring and pilot acceptance

Collect engine/guard heartbeat, last completed candle age, API errors/rate limits, open/pending orders, equity/exposure, rejection counts, entry-halt reason, process restarts, disk usage and backup status. Proposed alerts: missing heartbeat for 30 seconds once guard timing is validated; candle age over two strategy intervals; repeated order/API failures; guard latch; unreconciled fill; low disk space. Calibrate thresholds for the selected host/venue and record them.

Use local status/logs initially. Do not send email, chat or Telegram messages until the user supplies and authorizes a destination. Rotate logs and restrict permissions. Redact credentials, signatures, account identifiers where unnecessary and API response fields before publishing evidence.

Pilot acceptance requires the observation window and natural-trade coverage in B17, reproducible effective config, no unresolved safety errors, successful restart/outage/pause/backup drills, and a comparison of paper versus modeled behavior. Record uptime gaps. Paper success validates operation under simulated fills; real venue execution remains unproven.

## 5. Pause, outage and order-state incidents

**Entry pause:** latch the guard or manual entry gate, invoke the pinned verified entry-pause operation, inspect pending entries, cancel only entries and reconcile any fills. Continue exit/stop handling. An API pause acknowledgement alone does not establish that no pending order can fill.

**Process stop:** stopping a container or trader can also stop off-exchange exit supervision. Do not present it as equivalent to pausing entries. In paper mode, preserve state and test recovery. A future live process stop requires an operator decision about existing positions and verified protective orders; do not auto-liquidate them.

**Network/venue outage:** deny new entries through the freshness gate, use bounded retry/backoff, record last known orders, and alert. Do not retry unknown-state order submissions blindly. When connectivity returns, reconcile exchange orders/fills/balances before allowing entries. Keep an existing breach latched.

**Credential incident:** halt entries, revoke/rotate affected credentials through the owner's approved procedure, inspect order/account activity and preserve sanitized evidence. A revoked key may also disable exits; treat open-position protection as a separate incident obligation.

**Strategy/data anomaly:** halt entries, preserve the exact candle/input/config snapshot and software version, classify the cause, reproduce offline, and rerun relevant evidence before rearm. Avoid changing parameters mid-incident to chase recovery.

## 6. Backup, restore and updates

Back up the trade DB consistently using a database-supported backup method or a clean controlled stop; copying an active SQLite file without its transactional context is not a validated backup. Back up guard state, sanitized effective config, version manifest and incident/rearm audit with aligned timestamps. Encrypt and access-control any backup containing sensitive data. Proposed paper retention is daily snapshots for 7 days plus weekly snapshots for 4 weeks, adjusted to disk capacity; write a data retention decision before hosting.

Restore first into a separate paper environment with no trading keys and no shared mounts. Verify schema compatibility, open trades, processed fill IDs, guard latch and startup mode. For a later live restore, current exchange state is authoritative: reconciliation must precede entries because a restored DB may predate real fills. Never delete trades from a database to make reconciliation appear successful.

Before an engine update, back up, test the new pinned image/config in an isolated environment, run regression/bias checks and paper drills, then promote deliberately. Rollback requires a compatible database state and reconciliation, not merely changing the image tag. Keep the last tested release bundle and record the downgrade constraints.

## 7. Hosting and live decision

Hosting remains unselected. Local Docker is the development proposal; a single Linux host with Compose is a possible later always-on option after budget, uptime, maintenance, access and backup needs are agreed. No Kubernetes is required. Do not provision a paid host, expose the API publicly, or enable live operation as an automatic consequence of completing the backlog.

Present a final dossier: economic result including failures, dry-run evidence, exact image/source/config, venue limitations, approved proposed capital/limits, guard accounting and measured latency, operator coverage, deployment cost, backup/restore proof and residual risks. Then obtain a separate explicit live decision. No live-start command is supplied in this plan.
