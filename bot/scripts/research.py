"""Download, freeze and evaluate a credential-free spot dataset."""

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from preflight import BOT_DIR, read_settings, reject_environment_overrides, resolve_config

CONTAINER = "/project"
STRATEGY = "PersonalSpotBaseline"
SOURCE = BOT_DIR / "strategies" / f"{STRATEGY}.py"


def read_json(path):
    with path.open(encoding="utf-8") as stream:
        return read_settings(stream)


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def date_range(value):
    if not re.fullmatch(r"\d{8}-\d{8}", value):
        raise ValueError("date ranges must use YYYYMMDD-YYYYMMDD")
    start, end = (datetime.strptime(part, "%Y%m%d").replace(tzinfo=timezone.utc)
                  for part in value.split("-"))
    if start >= end or end > datetime.now(timezone.utc):
        raise ValueError("ranges must have a past UTC start and a later UTC end")
    return start, end


def docker(lock, dataset, writable=False, offline=False, output=None, entrypoint="freqtrade"):
    command = ["docker", "run", "--rm", "-i", "--platform", lock["platform"]]
    if offline:
        command += ["--network", "none"]
    command += [
        "--mount", f"type=bind,source={BOT_DIR / 'scripts'},target={CONTAINER}/scripts,readonly",
        "--mount", f"type=bind,source={BOT_DIR / 'strategies'},target={CONTAINER}/strategies,readonly",
        "--mount", f"type=bind,source={dataset},target=/dataset" + ("" if writable else ",readonly"),
    ]
    if output:
        command += ["--mount", f"type=bind,source={output},target=/results"]
    return command + ["--entrypoint", entrypoint, lock["image"]]


def freeze(lock, dataset, config, dates, timeframes):
    start, end = dates.split("-")
    files = []
    for timeframe in timeframes:
        names = [
            f"/dataset/{pair.replace('/', '_')}-{timeframe}.feather"
            for pair in config["exchange"]["pair_whitelist"]
        ]
        command = docker(lock, dataset, offline=True, entrypoint="python") + [
            f"{CONTAINER}/scripts/check_data.py", start, end,
            "--minutes", "60" if timeframe == "1h" else "5",
        ] + names
        result = subprocess.check_output(command, text=True)
        files.extend(json.loads(result))
    manifest = {
        "version": 1, "exchange": config["exchange"]["name"], "quote": config["stake_currency"],
        "pairs": config["exchange"]["pair_whitelist"], "timeframes": timeframes,
        "range_utc": dates, "format": "feather", "engine": lock,
        "frozen_at": datetime.now(timezone.utc).isoformat(), "files": files,
    }
    with (dataset / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")


def market_scope(config, dataset, lock):
    manifest_path = dataset / "manifest.json"
    manifest = read_json(manifest_path)
    pairs = config["exchange"]["pair_whitelist"]
    frames = manifest["timeframes"]
    if (
        manifest["exchange"] != config["exchange"]["name"] or manifest["quote"] != config["stake_currency"]
        or manifest["pairs"] != pairs or manifest["engine"]["image"] != lock["image"]
        or not frames or not set(frames) <= {"1h", "5m"} or "1h" not in frames
    ):
        raise ValueError("dataset does not match the configured market or pinned runtime")
    expected = {f"{pair.replace('/', '_')}-{tf}.feather" for tf in frames for pair in pairs}
    if {file["name"] for file in manifest["files"]} != expected:
        raise ValueError("dataset manifest has an incomplete file inventory")
    for file in manifest["files"]:
        path = dataset / file["name"]
        if path.is_symlink() or digest(path) != file["sha256"]:
            raise ValueError(f"dataset file differs from the frozen manifest: {path.name}")
    return manifest, digest(manifest_path)


def evaluate(args, lock, dataset, config):
    manifest, dataset_hash = market_scope(config, dataset, lock)
    protocol = read_json(args.protocol)
    settings_hash = fingerprint(config)
    strategy_hash = digest(SOURCE)
    if (
        protocol.get("dataset_manifest_sha256") != dataset_hash
        or protocol.get("effective_config_sha256") != settings_hash
        or protocol.get("strategy_sha256") != strategy_hash
    ):
        raise ValueError("record dataset, configuration and strategy hashes in the protocol first")
    windows = protocol["windows"]
    _, train_end = date_range(windows["train"])
    val_start, val_end = date_range(windows["validation"])
    test_start, _ = date_range(windows["test"])
    if not (train_end <= val_start and val_end <= test_start):
        raise ValueError("train, validation and untouched test ranges must be chronological")
    if not re.fullmatch(r"[a-z0-9-]+", args.window) or args.window not in windows:
        raise ValueError("window must be registered in the protocol")
    chosen = windows[args.window]
    start, end = date_range(chosen)
    if args.window not in {"train", "validation", "test"} and end > test_start:
        raise ValueError("walk-forward and diagnostic windows must precede the untouched test")
    first, last = date_range(manifest["range_utc"])
    warmup = 400 if args.action == "recursive-analysis" else 100
    if start < first + timedelta(hours=warmup) or end > last:
        raise ValueError("the frozen dataset must cover the whole window and startup candles")
    if args.window == "test" and (args.action != "backtesting" or args.fee_multiplier != 1 or args.detail):
        raise ValueError("the untouched test accepts only the frozen baseline backtest")
    fee = protocol["fee_per_side"]
    if type(fee) not in (float, int) or not 0 <= fee < 0.05:
        raise ValueError("register a fractional per-side fee below 5%")
    config = {**config, "fee": fee * args.fee_multiplier}

    if args.detail and "5m" not in manifest["timeframes"]:
        raise ValueError("detail backtesting needs audited 5m candles")
    pairs = config["exchange"]["pair_whitelist"]
    if args.action == "recursive-analysis" and args.pair not in pairs:
        raise ValueError("recursive analysis requires one pair from the frozen dataset")

    output_root = BOT_DIR / "runtime" / "research"
    output_root.mkdir(parents=True, exist_ok=True)
    protocol_hash = digest(args.protocol)
    if args.window == "test":
        # One attempt per dataset and test period, even if protocol settings are later edited.
        name = f"untouched-{dataset_hash[:12]}-{chosen}"
    else:
        name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + f"-{args.window}"
    output = output_root / name
    output.mkdir()
    # Freqtrade includes its end timestamp. Leave the next UTC window's opening candle out.
    end_inclusive = end - timedelta(minutes=1)
    engine_range = f"{start:%Y%m%d}-{end_inclusive:%Y%m%dT%H%M}"
    command = docker(lock, dataset, output=output) + [
        args.action, "-c", "-", "--userdir", "/results", "--strategy-path",
        f"{CONTAINER}/strategies", "--strategy", STRATEGY, "--datadir", "/dataset",
        "--timerange", engine_range,
    ]
    if args.action == "backtesting":
        command += [
            "--enable-protections", "--cache", "none", "--export", "trades", "--backtest-directory",
            "/results", "--fee", str(fee * args.fee_multiplier),
        ]
        if args.detail:
            command += ["--timeframe-detail", "5m"]
    elif args.action == "lookahead-analysis":
        command += [
            "--minimum-trade-amount", "10", "--targeted-trade-amount", "20", "--fee", str(fee),
            "--lookahead-analysis-exportfilename", "/results/lookahead.csv",
        ]
    else:
        command += ["-p", args.pair, "--startup-candle", "50", "100", "200", "400"]
    revision = subprocess.check_output(["git", "-C", str(BOT_DIR), "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "-C", str(BOT_DIR), "status", "--porcelain"]))
    run = {
        "status": "started", "command": command, "window": args.window, "engine": lock,
        "dataset_manifest_sha256": dataset_hash, "strategy_sha256": strategy_hash,
        "registered_config_sha256": settings_hash, "effective_config_sha256": fingerprint(config),
        "protocol_sha256": protocol_hash,
        "exchange": config["exchange"]["name"], "pairs": pairs, "range_utc": chosen,
        "fee_per_side": fee * args.fee_multiplier, "git_commit": revision, "git_dirty": dirty,
    }
    run_path = output / "run.json"
    run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    (output / "settings.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n", encoding="utf-8")
    print(f"Research evidence: {output}", flush=True)
    log_path = output / "engine.log"
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(command, input=json.dumps(config), text=True, stdout=log,
                                stderr=subprocess.STDOUT)
    diagnostic = args.action == "lookahead-analysis" and not (output / "lookahead.csv").is_file()
    missing_backtest = args.action == "backtesting" and not any(output.glob("backtest-result-*.zip"))
    # The pinned CLI may return zero after logging a configuration error.
    logged_error = "Configuration error:" in log_path.read_text(encoding="utf-8", errors="replace")
    returncode = result.returncode or int(missing_backtest or logged_error)
    run["status"] = (
        "engine_failed" if returncode else "inconclusive" if diagnostic else "engine_completed"
    )
    run["returncode"] = returncode
    run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    return returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("download", "freeze", "pins", "backtesting",
                                         "lookahead-analysis", "recursive-analysis"))
    parser.add_argument("settings", type=Path)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--range", dest="dates")
    parser.add_argument("--timeframes", nargs="+", choices=("1h", "5m"), default=["1h", "5m"])
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--window")
    parser.add_argument("--fee-multiplier", type=float, choices=(1, 1.5, 2), default=1)
    parser.add_argument("--detail", action="store_true")
    parser.add_argument("--pair")
    args = parser.parse_args()
    try:
        reject_environment_overrides()
        config = resolve_config(read_json(args.settings))
        config.pop("db_url")
        config["dataformat_ohlcv"] = "feather"
        lock = read_json(BOT_DIR / "VERSION.lock.json")
        dataset = args.dataset.absolute()
        if dataset.is_symlink():
            raise ValueError("use a real directory for the research dataset")
        if args.action in {"download", "freeze"}:
            date_range(args.dates or "")
            if "1h" not in args.timeframes or len(set(args.timeframes)) != len(args.timeframes):
                raise ValueError("timeframes must include 1h and may include 5m once")
            if (dataset / "manifest.json").exists():
                raise ValueError("dataset is frozen; choose a new directory")
            if args.action == "freeze":
                freeze(lock, dataset, config, args.dates, args.timeframes)
                return 0
            dataset.mkdir(parents=True, exist_ok=False)
            command = docker(lock, dataset, writable=True) + [
                "download-data", "-c", "-", "--userdir", "/dataset", "--datadir", "/dataset",
                "--timerange", args.dates, "--data-format-ohlcv", "feather",
                "--timeframes", *args.timeframes, "--pairs", *config["exchange"]["pair_whitelist"],
            ]
            return subprocess.run(command, input=json.dumps(config), text=True).returncode
        if args.action == "pins":
            _, manifest_hash = market_scope(config, dataset, lock)
            print(json.dumps({
                "dataset_manifest_sha256": manifest_hash, "effective_config_sha256": fingerprint(config),
                "strategy_sha256": digest(SOURCE),
            }, indent=2))
            return 0
        if args.protocol is None or not args.window:
            raise ValueError("evaluation requires --protocol and --window")
        return evaluate(args, lock, dataset, config)
    except (OSError, ValueError, TypeError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"Research command failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
