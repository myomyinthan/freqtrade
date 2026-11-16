"""Keep the dry-run paper pilot supervised on this Mac without a second writer.

Launchd user agents call this script. They adopt an already-running guard or
paper container, then replace themselves with that process when it exits.
Laptop sleep still invalidates a B17 continuous-uptime claim; these agents
only survive terminal close while the session stays awake.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOT_DIR = REPO_ROOT / "bot"
sys.path[:0] = [str(BOT_DIR / "scripts")]

import paper_status
import pilot_audit
from preflight import PAPER_DIR

STRATEGY = "PersonalSpotMacroBreakoutGuarded"
SETTINGS = BOT_DIR / "configs" / "pilot.local.json"
HOST_DIR = PAPER_DIR / "host"
AUDIT_DIR = PAPER_DIR / "audits"
DAILY_STAMP = AUDIT_DIR / "last-utc-day"
CONTAINER_NAME = "personalspot-paper-runner"
DAILY_SLOT_HOUR = 0
DAILY_SLOT_MINUTE = 15
DAILY_INTERVAL_SECONDS = 900

LABELS = {
    "guard": "com.personalspot.guard",
    "paper": "com.personalspot.paper",
    "daily": "com.personalspot.daily",
}

GUARD_ARGV_TAIL = ("bot/scripts/guard_runner.py", "watch")
PAPER_ARGV_TAIL = (
    "bot/scripts/preflight.py",
    "run",
    "--strategy",
    STRATEGY,
    "--local-api",
)


def is_guard_watch(command: str) -> bool:
    return "bot/scripts/guard_runner.py" in command and re.search(r"(^|\s)watch(\s|$)", command) is not None


def is_host_paper_launcher(command: str) -> bool:
    return (
        "bot/scripts/preflight.py" in command
        and "--inside" not in command
        and re.search(r"(^|\s)run(\s|$)", command) is not None
    )


def service_should_start(role: str, commands: list[str], container_running: bool) -> bool:
    if role == "guard":
        return not any(is_guard_watch(command) for command in commands)
    if role == "paper":
        if container_running or any(is_host_paper_launcher(command) for command in commands):
            return False
        return True
    raise ValueError(f"unsupported supervise role: {role}")


def utc_daily_due(
    now: datetime,
    stamp: str | None,
    *,
    hour: int = DAILY_SLOT_HOUR,
    minute: int = DAILY_SLOT_MINUTE,
) -> bool:
    current = now.astimezone(timezone.utc)
    slot = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if current < slot:
        return False
    return (stamp or "").strip() != current.date().isoformat()


def list_process_commands() -> list[str]:
    output = subprocess.check_output(["ps", "-ax", "-o", "command="], text=True, errors="replace")
    return output.splitlines()


def paper_container_running() -> bool:
    docker = shutil.which("docker")
    if not docker:
        return False
    proc = subprocess.run(
        [docker, "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0 and proc.stdout.strip().lower() == "true"


def _role_argv(role: str) -> list[str]:
    python = sys.executable
    if role == "guard":
        return [python, str(BOT_DIR / "scripts" / "guard_runner.py"), "watch", str(SETTINGS)]
    if role == "paper":
        return [
            python,
            str(BOT_DIR / "scripts" / "preflight.py"),
            "run",
            str(SETTINGS),
            "--strategy",
            STRATEGY,
            "--local-api",
        ]
    raise ValueError(f"unsupported supervise role: {role}")


def supervise(role: str, poll_seconds: float = 15.0) -> None:
    if role not in ("guard", "paper"):
        raise ValueError(f"unsupported supervise role: {role}")
    HOST_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_fd = os.open(HOST_DIR / f"{role}.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    while not service_should_start(role, list_process_commands(), paper_container_running()):
        time.sleep(poll_seconds)
    os.execv(sys.executable, _role_argv(role))


def _write_private_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")
    os.replace(temporary, path)


def run_daily_maintenance(now: datetime | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    stamp = DAILY_STAMP.read_text(encoding="utf-8") if DAILY_STAMP.is_file() else None
    if not utc_daily_due(current, stamp):
        return {"ran": False, "reason": "utc_daily_slot_not_due", "stamp": (stamp or "").strip() or None}

    paper_status.check_paper_paths("PersonalSpotBaseline")
    snapshot = paper_status.snapshot_and_rotate_backups()
    report = pilot_audit.run_pilot_audit(strategy_filter=STRATEGY)
    day = current.astimezone(timezone.utc).date().isoformat()
    destination = AUDIT_DIR / f"{day}.json"
    _write_private_json(destination, {
        "recorded_at_utc": current.astimezone(timezone.utc).isoformat(),
        "snapshot": snapshot,
        "pilot_audit": report,
    })
    fd = os.open(DAILY_STAMP, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(day + "\n")
    return {"ran": True, "audit": str(destination), "stamp": day, "verdict": report["b17_gate"]["verdict"]}


def operator_path() -> str:
    docker = shutil.which("docker")
    directories = []
    if docker:
        directories.append(str(Path(docker).resolve().parent))
    directories.extend(["/usr/local/bin", "/opt/homebrew/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    unique: list[str] = []
    for item in directories:
        if item not in unique:
            unique.append(item)
    return os.pathsep.join(unique)


def agent_plist(role: str, *, python: str, path_env: str, log_dir: Path) -> dict:
    if role not in LABELS:
        raise ValueError(f"unsupported agent role: {role}")
    script = str(Path(__file__).resolve())
    arguments = [python, script, "daily"] if role == "daily" else [python, script, "supervise", role]
    plist = {
        "Label": LABELS[role],
        "ProgramArguments": arguments,
        "WorkingDirectory": str(REPO_ROOT),
        "EnvironmentVariables": {"PATH": path_env},
        "StandardOutPath": str(log_dir / f"{role}.log"),
        "StandardErrorPath": str(log_dir / f"{role}.err"),
        "LimitLoadToSessionType": "Aqua",
        "RunAtLoad": True,
    }
    if role == "daily":
        plist["StartInterval"] = DAILY_INTERVAL_SECONDS
    else:
        plist["KeepAlive"] = True
        plist["ThrottleInterval"] = 15
    return plist


def launchd_blocked(text: str) -> bool:
    lowered = text.lower()
    return "operation not permitted" in lowered or "eperm" in lowered


def _bootout(domain: str, label: str) -> None:
    subprocess.run(
        ["launchctl", "bootout", f"{domain}/{label}"],
        capture_output=True,
        text=True,
    )


def _rollback_agents(domain: str, written: list[Path]) -> None:
    for destination in written:
        _bootout(domain, destination.stem)
        destination.unlink(missing_ok=True)


def install_agents() -> dict:
    host_dir = HOST_DIR
    host_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    agents = Path.home() / "Library" / "LaunchAgents"
    agents.mkdir(mode=0o700, parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    path_env = operator_path()
    written: list[Path] = []
    try:
        for role in ("guard", "paper", "daily"):
            plist = agent_plist(role, python=sys.executable, path_env=path_env, log_dir=host_dir)
            destination = agents / f"{LABELS[role]}.plist"
            err_log = host_dir / f"{role}.err"
            err_log.write_text("", encoding="utf-8")
            with destination.open("wb") as stream:
                plistlib.dump(plist, stream)
            os.chmod(destination, 0o644)
            written.append(destination)
            _bootout(domain, LABELS[role])
            proc = subprocess.run(
                ["launchctl", "bootstrap", domain, str(destination)],
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout).strip()
                raise ValueError(f"launchctl bootstrap {LABELS[role]} failed: {detail}")
            if role == "guard":
                time.sleep(1.5)
                probe = err_log.read_text(encoding="utf-8", errors="replace") if err_log.is_file() else ""
                if launchd_blocked(probe):
                    raise ValueError(
                        "macOS privacy blocked launchd from reading this repository. "
                        "Repositories under Documents, Desktop, or Downloads need Full Disk "
                        "Access for the launchd Python, or run `python3 bot/scripts/host_supervise.py session` "
                        "from Terminal or Cursor. Sleep still breaks the B17 continuous-uptime claim."
                    )
    except (OSError, ValueError) as exc:
        _rollback_agents(domain, written)
        raise ValueError(str(exc)) from exc
    return {
        "domain": domain,
        "installed": [str(path) for path in written],
        "continuity_note": (
            "Launchd keeps the dry-run alive across terminal close while this Mac session "
            "is awake. Sleep or a closed lid still breaks the B17 continuous-uptime claim."
        ),
    }


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_pid(path: Path) -> int | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return int(text) if text.isdigit() else None


def spawn_detached(argv: list[str], log_path: Path, err_path: Path, pid_path: Path) -> int:
    existing = _read_pid(pid_path)
    if existing is not None and _pid_alive(existing):
        return existing
    HOST_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    first = os.fork()
    if first > 0:
        os.waitpid(first, 0)
        for _ in range(50):
            spawned = _read_pid(pid_path)
            if spawned is not None and _pid_alive(spawned):
                return spawned
            time.sleep(0.05)
        raise ValueError(f"detached process did not record a pid in {pid_path}")
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    os.chdir(REPO_ROOT)
    out_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    err_fd = os.open(err_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.dup2(out_fd, 1)
    os.dup2(err_fd, 2)
    fd = os.open(pid_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(f"{os.getpid()}\n")
    os.execv(argv[0], argv)
    raise OSError("execv returned")


def start_session() -> dict:
    HOST_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    python = sys.executable
    script = str(Path(__file__).resolve())
    specs = {
        "guard": [python, script, "supervise", "guard"],
        "paper": [python, script, "supervise", "paper"],
        "daily": [python, script, "daily-loop"],
    }
    pids = {}
    for role, argv in specs.items():
        pids[role] = spawn_detached(
            argv,
            HOST_DIR / f"{role}.session.log",
            HOST_DIR / f"{role}.session.err",
            HOST_DIR / f"{role}.session.pid",
        )
    return {
        "pids": pids,
        "continuity_note": (
            "Session supervisors were started from an authorized process. They survive "
            "terminal close while the Mac stays awake, and they stop on reboot or sleep. "
            "That does not satisfy the B17 continuous-uptime claim."
        ),
    }


def daily_loop(poll_seconds: float = DAILY_INTERVAL_SECONDS) -> None:
    while True:
        try:
            result = run_daily_maintenance()
            print(json.dumps(result), flush=True)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            print(f"Daily maintenance failed: {exc}", file=sys.stderr, flush=True)
        time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "supervise", "daily", "daily-loop", "session"))
    parser.add_argument("role", nargs="?", choices=("guard", "paper"))
    args = parser.parse_args()
    try:
        if args.action == "install":
            print(json.dumps(install_agents(), indent=2))
            return 0
        if args.action == "supervise":
            if args.role is None:
                parser.error("supervise requires guard or paper")
            supervise(args.role)
            return 0
        if args.action == "session":
            print(json.dumps(start_session(), indent=2))
            return 0
        if args.action == "daily-loop":
            daily_loop()
            return 0
        result = run_daily_maintenance()
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Host supervise failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
