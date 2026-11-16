# macOS `launchd` User Agents (Laptop Session Only)

These agents keep the credential-free `H003` dry-run (`PersonalSpotMacroBreakoutGuarded`) supervised in the current Aqua login session:

- `com.personalspot.guard` — adopts a running `guard_runner.py watch`, then restarts it if it exits
- `com.personalspot.paper` — adopts `personalspot-paper-runner` if it is already up, and starts it through `preflight.py` only after it exits
- `com.personalspot.daily` — after `00:15 UTC`, once per UTC day, runs `snapshot-rotate` and appends `pilot_audit.py` under `bot/runtime/paper/audits/`

Sleep, a closed lid, or shutdown still breaks the `B17` continuous-uptime claim. An always-on Linux host uses `bot/deploy/systemd/` instead. These agents contain no exchange keys, open no host ports, and do not enable live trading.

`python3 bot/scripts/host_supervise.py install` loads the three user agents. If this repository sits under `Documents`, `Desktop`, or `Downloads`, macOS blocks `launchd` from reading it (`Operation not permitted`). `install` removes the agents again when that happens. Grant Full Disk Access to the Command Line Tools Python before retrying, or start supervisors from an already authorized Terminal or Cursor session:

```sh
python3 bot/scripts/host_supervise.py session
```

`session` adopts the running guard and paper container and repeats the UTC daily snapshot/audit every 15 minutes. Those processes survive closing the terminal while the Mac stays awake. They do not survive reboot or sleep, so they do not make the `B17` window continuous.

Logs and lock files stay in the ignored runtime directory `bot/runtime/paper/host/`.
