# Personal spot bot

This directory contains the Milestone 0 scaffold for the personal Freqtrade fork. The Git base is release 2026.10 and Compose uses the corresponding ARM64 image by digest. [Version lock](VERSION.lock.json)

The paper launcher defaults to the inert `PaperScaffold` fixture. Select `--strategy PersonalSpotBaseline` to load H001, the long-only hourly SMA20/SMA50 crossover. It uses a separate paper database.

## Check the scaffold

Run these commands from the fork root. The pinned image also runs the tests that require Freqtrade and Feather support.

```sh
python3 -m unittest discover -s bot/tests -v
docker-compose --env-file /dev/null -p personalspot-paper -f bot/compose.yaml config --quiet
image=$(python3 -c 'import json; print(json.load(open("bot/VERSION.lock.json"))["image"])')
docker run --rm --network none --entrypoint python \
  -v "$PWD/bot:/project:ro" "$image" -m unittest discover -s /project/tests -v
```

Use `docker compose` in the second command if the plugin is available. The launcher detects the installed variant.

## Supply paper settings

Copy `bot/configs/pilot.example.json` to `bot/configs/pilot.local.json`. Set the selected exchange ID, quote currency, explicit spot pairs, simulated wallet and fixed stake per position. The local filename is ignored by Git. Preflight checks the shape of those inputs, and venue availability, trading limits and fees are verified in Milestone 1.

```sh
python3 bot/scripts/preflight.py check bot/configs/pilot.local.json
python3 bot/scripts/preflight.py verify bot/configs/pilot.local.json
```

`check` validates the merged config without Docker. `verify` checks the pinned engine schema, strategy loader and writable runtime mount without running the trader. The launcher rejects `FREQTRADE__` overrides and supplies one validated configuration to Freqtrade over stdin. The paper SQLite files and launch manifests are under `bot/runtime/paper/`. Each launch manifest records the Git revision, dirty state, engine pin and effective config hash.

## Freeze data and run research

The example assumes two shell variables containing the concrete date range and a new dataset directory. Include 100 hours of hourly warmup before the earliest backtest, or 400 hours before the recursive analysis window. Use a timeframe list the venue can provide and document any dataset imported from the venue's published archive.

```sh
settings=bot/configs/pilot.local.json
python3 bot/scripts/research.py download "$settings" "$dataset" --range "$download_range"
python3 bot/scripts/research.py freeze "$settings" "$dataset" --range "$download_range"
python3 bot/scripts/research.py pins "$settings" "$dataset"
```

Copy `bot/configs/protocol.example.json` to `bot/configs/protocol.local.json`. Register the hashes printed by `pins`, the verified per-side fee, UTC date windows, and screening thresholds before reading strategy results. A date range uses `YYYYMMDD-YYYYMMDD`. Add named walk-forward or diagnostic windows before the untouched test. [Research protocol](docs/plans/03_RESEARCH_AND_VALIDATION.md)

```sh
protocol=bot/configs/protocol.local.json
python3 bot/scripts/research.py backtesting "$settings" "$dataset" --protocol "$protocol" --window train
python3 bot/scripts/research.py lookahead-analysis "$settings" "$dataset" --protocol "$protocol" --window validation
python3 bot/scripts/research.py recursive-analysis "$settings" "$dataset" --protocol "$protocol" --window validation --pair "$pair"
```

Use `--fee-multiplier 1.5` and `2` for fee stress, and `--detail` for the 5m comparison. Run these on development windows. Results, logs and input fingerprints are stored under `bot/runtime/research/`. Review lookahead trade coverage and recursive output before interpreting results. `report_results.py <archive>` summarizes trades and adverse fill costs. Run it inside the pinned image with `--dataset <mounted dataset>` to include the equal-weight buy-and-hold benchmark.

## Operate the paper bot

Use the selected exchange settings to run the baseline schema check. Pass `--local-api` to enable the authenticated container-loopback (`127.0.0.1:8080`, zero host ports) control interface used for live candle freshness, entry pause/resume, and pending-entry reconciliation. Stop the process with Ctrl+C or `docker stop personalspot-paper-runner`.

```sh
python3 bot/scripts/preflight.py verify "$settings" --strategy PersonalSpotBaseline --local-api
python3 bot/scripts/preflight.py run "$settings" --strategy PersonalSpotBaseline --local-api
python3 bot/scripts/paper_status.py status
python3 bot/scripts/paper_status.py pause
python3 bot/scripts/paper_status.py resume
python3 bot/scripts/paper_status.py backup bot/runtime/paper/morning.backup.sqlite
python3 bot/scripts/paper_status.py verify-backup bot/runtime/paper/morning.backup.sqlite
python3 bot/scripts/paper_status.py restore-drill bot/runtime/paper/morning.backup.sqlite /tmp/paper-restore-check
python3 bot/scripts/paper_status.py export bot/runtime/paper/sanitized-status.json
```

`status` reports container health, SQLite positions/orders, rotating logs, guard state, local alerts (`failed_heartbeat`, `stale_feed`, `repeated_errors`, `disk_pressure`, `restart_detected`, `guard_latched`, `guard_stale`), and free disk space.

## Operate with the persisted daily entry-halt guard (`M4`)

Initialize `guard.policy.json`, register the UTC day baseline when starting mid-day on a reconciled ledger, keep `guard_runner.py watch` running in a separate process (`10s` poll, `30s` lease), and launch `--strategy PersonalSpotGuarded --local-api`. It halts new entries fail-closed without claiming a guaranteed monetary loss ceiling on open positions.

```sh
python3 bot/scripts/guard_runner.py init "$settings" --max-loss-quote 25 --max-age-seconds 30 --poll-interval-seconds 10
python3 bot/scripts/guard_runner.py bootstrap-day "$settings" --reason "initial UTC day paper baseline"
python3 bot/scripts/guard_runner.py watch "$settings"
python3 bot/scripts/preflight.py run "$settings" --strategy PersonalSpotGuarded --local-api
```

Reports and runbooks: [H001 research report](docs/research/H001-binance-usdt-spot-report.md), [M3 smoke & drills](docs/operations/M3-paper-smoke-and-drills.md), [M4 guard & deployment guide](docs/operations/M4-guard-and-deployment-guide.md), and [Live-boundary decision dossier](docs/operations/M4-decision-dossier.md).
