"""Validate the paper configuration, then launch through a fixed Compose service."""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parents[1]
PAPER_DIR = BOT_DIR / "runtime" / "paper"
DB_NAME = "trades.paper.sqlite"
BASELINE_DB_NAME = "baseline.paper.sqlite"
API_AUTH_NAME = "api.auth.json"
GUARD_POLICY_NAME = "guard.policy.json"
GUARD_STATE_NAME = "guard.state.json"
RUNNER_LOCK_NAME = "runner.lock"
LOG_REL_PATH = "logs/freqtrade.paper.log"
CONTAINER_USERDIR = "/freqtrade/bot/runtime/paper"
DB_URL = f"sqlite:///{CONTAINER_USERDIR}/{DB_NAME}"
STRATEGY = "PaperScaffold"
GUARDED_STRATEGY = "PersonalSpotGuarded"
STRATEGIES = (STRATEGY, "PersonalSpotBaseline", GUARDED_STRATEGY)
STATES = ("running", "paused")
SETTINGS = {"exchange", "stake_currency", "stake_amount", "dry_run_wallet"}


def unique_object(items):
    obj = {}
    for key, value in items:
        if key in obj:
            raise ValueError("JSON contains a duplicate key")
        obj[key] = value
    return obj


def read_settings(stream):
    config = json.load(stream, object_pairs_hook=unique_object)
    if not isinstance(config, dict):
        raise ValueError("expected a JSON object")
    return config


def reject_environment_overrides():
    if any(key.startswith("FREQTRADE__") for key in os.environ):
        raise ValueError("unset FREQTRADE__ configuration overrides before using this launcher")


def resolve_config(settings, strategy=STRATEGY, initial_state="running"):
    with (BOT_DIR / "configs" / "base.example.json").open(encoding="utf-8") as stream:
        config = read_settings(stream)
    exchange = settings.get("exchange")
    if set(settings) - SETTINGS:
        raise ValueError("paper overrides may only set exchange, quote, stake and paper wallet")
    if not isinstance(exchange, dict) or set(exchange) - {"name", "pair_whitelist"}:
        raise ValueError("exchange overrides may only set the exchange ID and spot pairs")
    if initial_state not in STATES:
        raise ValueError("initial_state must be running or paused")

    config.update({key: settings[key] for key in SETTINGS - {"exchange"} if key in settings})
    config["exchange"].update(exchange)
    config["initial_state"] = initial_state

    if config.get("dry_run") is not True or config.get("trading_mode") != "spot":
        raise ValueError("the resolved configuration must enable dry-run and use spot mode")
    if config.get("force_entry_enable") is not False:
        raise ValueError("force entry must be disabled")
    if config.get("position_adjustment_enable") is not False:
        raise ValueError("position adjustment must be disabled")
    if config.get("db_url") != DB_URL:
        raise ValueError("the resolved configuration must use the dedicated paper database")
    if "add_config_files" in config:
        raise ValueError("paper configuration must be self-contained")
    if strategy != STRATEGY:
        config["db_url"] = f"sqlite:///{CONTAINER_USERDIR}/{BASELINE_DB_NAME}"

    name = config["exchange"].get("name")
    quote = config.get("stake_currency")
    pairs = config["exchange"].get("pair_whitelist")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9]*", name):
        raise ValueError("set the selected exchange ID")
    if not isinstance(quote, str) or not re.fullmatch(r"[A-Z0-9]+", quote):
        raise ValueError("set the selected quote currency")
    if not isinstance(pairs, list) or not pairs or any(
        not isinstance(pair, str) or not re.fullmatch(r"[A-Z0-9]+/" + quote, pair)
        for pair in pairs
    ):
        raise ValueError("set a nonempty spot pairlist matching the selected quote currency")
    if len(set(pairs)) != len(pairs):
        raise ValueError("spot pairs must be unique")
    for key in ("dry_run_wallet", "stake_amount"):
        value = config.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be a positive finite number")
    available = config["dry_run_wallet"] * config["tradable_balance_ratio"]
    if config["stake_amount"] * config["max_open_trades"] > available:
        raise ValueError("paper wallet must cover the fixed stake for all open slots")
    return config


def _check_regular_unlinked(path: Path, label: str):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"{label} must be regular, unlinked files")


def check_paper_paths(strategy=STRATEGY):
    for directory in (PAPER_DIR.parent, PAPER_DIR, PAPER_DIR / "logs"):
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise ValueError("paper runtime directories must be regular directories")
    for suffix in ("", "-wal", "-shm", "-journal"):
        db_name = DB_NAME if strategy == STRATEGY else BASELINE_DB_NAME
        _check_regular_unlinked(PAPER_DIR / (db_name + suffix), "paper database files")
    for name in (API_AUTH_NAME, GUARD_POLICY_NAME, GUARD_STATE_NAME, RUNNER_LOCK_NAME):
        _check_regular_unlinked(PAPER_DIR / name, "paper runtime control files")


def check_guard_readiness(config, mode):
    sys.path.insert(0, str(BOT_DIR / "risk"))
    from decimal import Decimal
    from datetime import timedelta
    from guard import Guard

    policy_path = PAPER_DIR / GUARD_POLICY_NAME
    state_path = PAPER_DIR / GUARD_STATE_NAME
    _check_regular_unlinked(policy_path, "paper runtime control files")
    _check_regular_unlinked(state_path, "paper runtime control files")
    if not policy_path.is_file():
        raise ValueError(
            "PersonalSpotGuarded requires bot/runtime/paper/guard.policy.json; initialize guard_runner.py first"
        )
    with policy_path.open(encoding="utf-8") as stream:
        policy = read_settings(stream)
    expected_account = f"paper:{config['exchange']['name']}:{config['stake_currency']}"
    if policy.get("account") != expected_account:
        raise ValueError(
            f"guard.policy.json account {policy.get('account')!r} does not match {expected_account!r}"
        )
    max_loss = Decimal(str(policy["max_loss_quote"]))
    max_age = timedelta(seconds=float(policy["max_age_seconds"]))
    ratio_raw = policy.get("max_loss_ratio")
    ratio = Decimal(str(ratio_raw)) if ratio_raw is not None else None
    guard = Guard(state_path, expected_account, max_loss, max_age, max_loss_ratio=ratio)
    if mode == "run" and config.get("initial_state") == "running":
        if not guard.entries_allowed(datetime.now(timezone.utc)):
            raise ValueError(
                "PersonalSpotGuarded refused running launch: guard state is missing, stale or latched"
            )
    return policy


def ensure_api_auth():
    auth_path = PAPER_DIR / API_AUTH_NAME
    _check_regular_unlinked(auth_path, "paper runtime control files")
    if auth_path.exists():
        os.chmod(auth_path, 0o600)
        with auth_path.open(encoding="utf-8") as stream:
            auth = read_settings(stream)
        if all(
            isinstance(auth.get(key), str) and len(auth[key]) >= 12
            for key in ("username", "password", "jwt_secret_key", "ws_token")
        ):
            return auth
        raise ValueError("existing api.auth.json is invalid; remove or regenerate it")

    payload = {
        "username": "paper-operator",
        "password": secrets.token_urlsafe(32),
        "jwt_secret_key": secrets.token_hex(32),
        "ws_token": secrets.token_urlsafe(32),
    }
    fd = os.open(auth_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")
    return payload


def api_server_config():
    auth_path = PAPER_DIR / API_AUTH_NAME
    _check_regular_unlinked(auth_path, "paper runtime control files")
    with auth_path.open(encoding="utf-8") as stream:
        auth = read_settings(stream)
    for key in ("username", "password", "jwt_secret_key", "ws_token"):
        if not isinstance(auth.get(key), str) or len(auth[key]) < 12:
            raise ValueError(f"api.auth.json missing valid {key}")
    return {
        "enabled": True,
        "listen_ip_address": "127.0.0.1",
        "listen_port": 8080,
        "verbosity": "error",
        "enable_openapi": False,
        "jwt_secret_key": auth["jwt_secret_key"],
        "ws_token": auth["ws_token"],
        "CORS_origins": [],
        "username": auth["username"],
        "password": auth["password"],
    }


@contextmanager
def single_writer_lock():
    lock_path = PAPER_DIR / RUNNER_LOCK_NAME
    _check_regular_unlinked(lock_path, "paper runtime control files")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a+", encoding="utf-8") as lock_stream:
        try:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(
                "another paper runner already holds runner.lock; duplicate writers are forbidden"
            ) from exc
        lock_stream.seek(0)
        lock_stream.truncate()
        lock_stream.write(f"{os.getpid()}\n")
        lock_stream.flush()
        try:
            yield
        finally:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)


def compose_command(env):
    if shutil.which("docker"):
        plugin = subprocess.run(["docker", "compose", "version"], env=env, capture_output=True)
        if plugin.returncode == 0:
            return ["docker", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    raise ValueError("Docker Compose is required")


def record_launch(config, command, strategy=STRATEGY, local_api=False):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(BOT_DIR), *args], text=True).strip()

    sanitized = {key: value for key, value in config.items() if key != "api_server"}
    payload = json.dumps(sanitized, sort_keys=True, allow_nan=False).encode("utf-8")
    with (BOT_DIR / "VERSION.lock.json").open(encoding="utf-8") as stream:
        version = read_settings(stream)
    manifest = {
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "overlay_commit": git("rev-parse", "HEAD"),
        "overlay_dirty": bool(git("status", "--porcelain")),
        "engine": version,
        "command": command,
        "config_sha256": hashlib.sha256(payload).hexdigest(),
        "strategy": strategy,
        "initial_state": sanitized["initial_state"],
        "local_api_enabled": bool(local_api),
        "guard_enforcement": (
            "persisted_entry_halt_active_not_hard_loss_guarantee"
            if strategy == GUARDED_STRATEGY
            else "not_integrated_no_daily_loss_enforcement_claimed"
        ),
    }
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="launch-", suffix=".json",
        dir=PAPER_DIR, delete=False,
    ) as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")


def run_container(mode, settings, config, strategy, initial_state="running", local_api=False):
    env = {key: value for key, value in os.environ.items() if not key.startswith("COMPOSE_")}
    command = compose_command(env) + [
        "--env-file", "/dev/null", "-p", "personalspot-paper", "-f", str(BOT_DIR / "compose.yaml"),
        "run", "--rm", "--no-deps", "-T",
    ]
    if mode == "run":
        command.extend(["--name", "personalspot-paper-runner"])
    command.extend([
        "--entrypoint", "python", "freqtrade", "/freqtrade/bot/scripts/preflight.py",
        "--inside", mode, "--strategy", strategy, "--state", initial_state,
    ])
    if local_api:
        command.append("--local-api")
    if mode == "run":
        record_launch(config, command, strategy=strategy, local_api=local_api)
    return subprocess.run(command, input=json.dumps(settings), text=True, env=env).returncode


def engine(mode, strategy_name, initial_state="running", local_api=False):
    # Validate the same settings inside the container before passing a single config to the engine.
    config = resolve_config(read_settings(sys.stdin), strategy_name, initial_state)
    check_paper_paths(strategy_name)
    if strategy_name == GUARDED_STRATEGY:
        if mode == "run" and not local_api:
            raise ValueError("PersonalSpotGuarded requires --local-api for entry-pause enforcement")
        check_guard_readiness(config, mode)
    if local_api:
        config["api_server"] = api_server_config()
    if mode == "verify":
        from freqtrade.configuration.config_validation import validate_config_consistency
        from freqtrade.enums import RunMode
        from freqtrade.exchange.check_exchange import check_exchange
        from freqtrade.resolvers import StrategyResolver

        with tempfile.TemporaryFile(dir=PAPER_DIR):
            pass
        config.update(
            runmode=RunMode.DRY_RUN,
            user_data_dir=PAPER_DIR,
            strategy_path=str(BOT_DIR / "strategies"),
            strategy=strategy_name,
        )
        check_exchange(config)
        strategy = StrategyResolver.load_strategy(config)
        validate_config_consistency(config)
        if strategy_name == STRATEGY and strategy.confirm_trade_entry() is not False:
            raise ValueError("the Milestone 0 strategy fixture must reject entries")
        print(f"Pinned Freqtrade dry-run schema and {strategy_name} loading checks passed.")
        return 0

    # A temporary stdin stream gives Freqtrade exactly the configuration we validated.
    with tempfile.TemporaryFile() as stream:
        stream.write(json.dumps(config, allow_nan=False).encode("utf-8"))
        stream.seek(0)
        os.dup2(stream.fileno(), 0)
        os.execvp("freqtrade", [
            "freqtrade", "trade", "-c", "-",
            "--logfile", f"{CONTAINER_USERDIR}/{LOG_REL_PATH}",
            "--userdir", CONTAINER_USERDIR,
            "--strategy-path", str(BOT_DIR / "strategies"), "--strategy", strategy_name,
        ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "verify", "run"))
    parser.add_argument("settings", nargs="?", type=Path)
    parser.add_argument("--strategy", choices=STRATEGIES, default=STRATEGY)
    parser.add_argument("--state", choices=STATES, default="running")
    parser.add_argument(
        "--local-api", action="store_true",
        help="enable authenticated 127.0.0.1:8080 control API inside the container namespace",
    )
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        reject_environment_overrides()
        if args.inside and args.mode in ("verify", "run") and args.settings is None:
            return engine(args.mode, args.strategy, args.state, args.local_api)
        if args.inside or args.settings is None:
            parser.error("provide the path to paper settings")
        with args.settings.open(encoding="utf-8") as stream:
            settings = read_settings(stream)
        config = resolve_config(settings, args.strategy, args.state)
        check_paper_paths(args.strategy)
        if args.strategy == GUARDED_STRATEGY:
            if args.mode == "run" and not args.local_api:
                raise ValueError("PersonalSpotGuarded requires --local-api for entry-pause enforcement")
            if args.mode in ("check", "run"):
                check_guard_readiness(config, args.mode)
        if args.mode == "check":
            print("Resolved spot dry-run configuration passed preflight.")
            return 0
        PAPER_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        (PAPER_DIR / "logs").mkdir(mode=0o700, parents=True, exist_ok=True)
        if args.local_api:
            ensure_api_auth()
        if args.mode == "run":
            with single_writer_lock():
                return run_container(
                    args.mode, settings, config, args.strategy, args.state, args.local_api,
                )
        return run_container(
            args.mode, settings, config, args.strategy, args.state, args.local_api,
        )
    except (OSError, ValueError, OverflowError, subprocess.CalledProcessError) as exc:
        print(f"Paper preflight failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
