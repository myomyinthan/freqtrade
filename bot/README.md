# Personal spot bot

This directory contains the Milestone 0 scaffold for the personal Freqtrade fork. The Git base is release 2026.10 and Compose uses the corresponding ARM64 image by digest. [Version lock](VERSION.lock.json)

The paper launcher uses `PaperScaffold`, an inert fixture that emits zero entry signals and rejects entry requests. The trading strategy is Milestone 1. This scaffold reads public market data if you explicitly start it with valid venue settings.

## Check the scaffold

Run these commands from the fork root. The preflight tests use only Python's standard library.

```sh
python3 -m unittest discover -s bot/tests -v
docker-compose --env-file /dev/null -p personalspot-paper -f bot/compose.yaml config --quiet
```

Use `docker compose` in the second command if the plugin is available. The launcher detects the installed variant.

## Supply paper settings

Copy `bot/configs/pilot.example.json` to `bot/configs/pilot.local.json`. Set the selected exchange ID, quote currency, explicit spot pairs, simulated wallet and fixed stake per position. The local filename is ignored by Git. Preflight checks the shape of those inputs, and venue availability, trading limits and fees are verified in Milestone 1.

```sh
python3 bot/scripts/preflight.py check bot/configs/pilot.local.json
python3 bot/scripts/preflight.py verify bot/configs/pilot.local.json
```

`check` validates the merged config without Docker. `verify` checks the pinned engine schema, strategy loader and writable runtime mount without running the trader. The launcher rejects `FREQTRADE__` overrides and supplies one validated configuration to Freqtrade over stdin. The paper SQLite files and launch manifests are under `bot/runtime/paper/`. Each launch manifest records the Git revision, dirty state, engine pin and effective config hash.

Once an exchange and paper settings are selected, use `python3 bot/scripts/preflight.py run bot/configs/pilot.local.json` for the inert dry-run process. Stop it with Ctrl+C. The service's default Compose command reports the engine version. [Implementation plan](docs/plans/README.md)
