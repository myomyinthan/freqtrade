# Single-Host Linux `systemd` Bundle (`B20` — Paper Pilot Only)

This directory packages hardened rootless/user `systemd` units for running the **credential-free `H003` (`PersonalSpotMacroBreakoutGuarded`) dry-run paper pilot** continuously on an always-on Linux host (`~/freqtrade`) so a sleeping laptop does not interrupt the `30`-day `B17` observation window.

> **Scope & Safety:** These units contain **zero exchange API keys**, expose **zero host ports**, enforce `UMask=0077` and `NoNewPrivileges=yes`, and start strictly through `preflight.py` (`dry_run=true`, `trading_mode=spot`, `force_entry_enable=false`). No paid cloud host is provisioned automatically.

## 1. Architecture Note (`linux/arm64` vs. `linux/amd64`)

`bot/VERSION.lock.json` and `bot/compose.yaml` pin the verified `linux/arm64` digest of `freqtradeorg/freqtrade:2026.10` (`sha256:1bb9a6b11a4dae39444331aa324b139dcd635f6a1c586ce9ecccac17994edc0c`).
- On an **ARM64** Linux host, use the lockfile as-is.
- On an **x86_64 (`linux/amd64`)** Linux host, inspect the official multi-arch manifest for `docker.io/freqtradeorg/freqtrade:2026.10`, record the immutable `linux/amd64` SHA-256 digest in `bot/VERSION.lock.json` and `bot/compose.yaml`, and re-run the offline container test suite before starting the service.

## 2. Install & Start (User `systemd` Instance)

Assumes the repository is cloned at `~/freqtrade` on `bot/main`, `~/freqtrade/bot/configs/pilot.local.json` is populated (`0600`, no credentials), and the operator can invoke Docker Compose:

```sh
cd ~/freqtrade

# 1. Run offline unit & container checks first
image=$(python3 -c 'import json; print(json.load(open("bot/VERSION.lock.json"))["image"])')
docker run --rm --network none --entrypoint python \
  -v "$PWD/bot:/project:ro" "$image" -m unittest discover -s /project/tests -v

# 2. Initialize & bootstrap the M4 daily entry-halt guard
python3 bot/scripts/guard_runner.py init bot/configs/pilot.local.json \
  --max-loss-quote 25 --max-age-seconds 30 --poll-interval-seconds 10
python3 bot/scripts/guard_runner.py bootstrap-day bot/configs/pilot.local.json \
  --reason "initial single-host paper baseline registration"

# 3. Install user units and enable lingering across SSH logouts
mkdir -p ~/.config/systemd/user
cp bot/deploy/systemd/personalspot-*.service bot/deploy/systemd/personalspot-*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
sudo loginctl enable-linger "$USER"

# 4. Start guard first, then paper runner and daily backup timer
systemctl --user enable --now personalspot-guard.service
systemctl --user enable --now personalspot-paper.service
systemctl --user enable --now personalspot-backup.timer
```

## 3. Daily Verification & Incident Checks

```sh
systemctl --user status personalspot-guard.service personalspot-paper.service personalspot-backup.timer
python3 ~/freqtrade/bot/scripts/paper_status.py digest
python3 ~/freqtrade/bot/scripts/pilot_audit.py --strategy PersonalSpotMacroBreakoutGuarded
```
