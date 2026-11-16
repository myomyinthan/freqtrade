"""Validate the paper configuration, then launch through a fixed Compose service."""

import argparse
import hashlib
import json
import math
import os
import re
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
CONTAINER_USERDIR = "/freqtrade/bot/runtime/paper"
DB_URL = f"sqlite:///{CONTAINER_USERDIR}/{DB_NAME}"
STRATEGY = "PaperScaffold"
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


def resolve_config(settings):
    with (BOT_DIR / "configs" / "base.example.json").open(encoding="utf-8") as stream:
        config = read_settings(stream)
    exchange = settings.get("exchange")
    if set(settings) - SETTINGS:
        raise ValueError("paper overrides may only set exchange, quote, stake and paper wallet")
    if not isinstance(exchange, dict) or set(exchange) - {"name", "pair_whitelist"}:
        raise ValueError("exchange overrides may only set the exchange ID and spot pairs")

    config.update({key: settings[key] for key in SETTINGS - {"exchange"} if key in settings})
    config["exchange"].update(exchange)

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


def check_paper_paths():
    for directory in (PAPER_DIR.parent, PAPER_DIR):
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise ValueError("paper runtime directories must be regular directories")
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = PAPER_DIR / (DB_NAME + suffix)
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("paper database files must be regular, unlinked files")


def compose_command(env):
    if shutil.which("docker"):
        plugin = subprocess.run(["docker", "compose", "version"], env=env, capture_output=True)
        if plugin.returncode == 0:
            return ["docker", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    raise ValueError("Docker Compose is required")


def record_launch(config, command):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(BOT_DIR), *args], text=True).strip()

    payload = json.dumps(config, sort_keys=True, allow_nan=False).encode("utf-8")
    with (BOT_DIR / "VERSION.lock.json").open(encoding="utf-8") as stream:
        version = read_settings(stream)
    manifest = {
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "overlay_commit": git("rev-parse", "HEAD"),
        "overlay_dirty": bool(git("status", "--porcelain")),
        "engine": version,
        "command": command,
        "config_sha256": hashlib.sha256(payload).hexdigest(),
    }
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="launch-", suffix=".json",
        dir=PAPER_DIR, delete=False,
    ) as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")


def run_container(mode, settings, config):
    env = {key: value for key, value in os.environ.items() if not key.startswith("COMPOSE_")}
    command = compose_command(env) + [
        "--env-file", "/dev/null", "-p", "personalspot-paper", "-f", str(BOT_DIR / "compose.yaml"),
        "run", "--rm", "--no-deps", "-T",
    ]
    if mode == "run":
        command.extend(["--name", "personalspot-paper-runner"])
    command.extend([
        "--entrypoint", "python", "freqtrade", "/freqtrade/bot/scripts/preflight.py",
        "--inside", mode,
    ])
    if mode == "run":
        record_launch(config, command)
    return subprocess.run(command, input=json.dumps(settings), text=True, env=env).returncode


def engine(mode):
    # Validate the same settings inside the container before passing a single config to the engine.
    config = resolve_config(read_settings(sys.stdin))
    check_paper_paths()
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
            strategy=STRATEGY,
        )
        check_exchange(config)
        strategy = StrategyResolver.load_strategy(config)
        validate_config_consistency(config)
        if strategy.confirm_trade_entry() is not False:
            raise ValueError("the Milestone 0 strategy fixture must reject entries")
        print("Pinned Freqtrade dry-run schema and inert strategy checks passed.")
        return 0

    # A temporary stdin stream gives Freqtrade exactly the configuration we validated.
    with tempfile.TemporaryFile() as stream:
        stream.write(json.dumps(config, allow_nan=False).encode("utf-8"))
        stream.seek(0)
        os.dup2(stream.fileno(), 0)
        os.execvp("freqtrade", [
            "freqtrade", "trade", "-c", "-", "--userdir", CONTAINER_USERDIR,
            "--strategy-path", str(BOT_DIR / "strategies"), "--strategy", STRATEGY,
        ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "verify", "run"))
    parser.add_argument("settings", nargs="?", type=Path)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        reject_environment_overrides()
        if args.inside and args.mode in ("verify", "run") and args.settings is None:
            return engine(args.mode)
        if args.inside or args.settings is None:
            parser.error("provide the path to paper settings")
        with args.settings.open(encoding="utf-8") as stream:
            settings = read_settings(stream)
        config = resolve_config(settings)
        check_paper_paths()
        if args.mode == "check":
            print("Resolved spot dry-run configuration passed preflight.")
            return 0
        PAPER_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        return run_container(args.mode, settings, config)
    except (OSError, ValueError, OverflowError, subprocess.CalledProcessError) as exc:
        print(f"Paper preflight failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
