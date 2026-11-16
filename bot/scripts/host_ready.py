"""Report whether this machine can install the dry-run systemd bundle.

This check does not start services, copy unit files, or create a host.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BOT_DIR / "scripts")]

from preflight import read_settings

LOCK_PATH = BOT_DIR / "VERSION.lock.json"


def normalize_platform(system: str, machine: str) -> str | None:
    if system.lower() != "linux":
        return None
    normalized = machine.lower()
    if normalized in {"x86_64", "amd64"}:
        return "linux/amd64"
    if normalized in {"aarch64", "arm64"}:
        return "linux/arm64"
    return None


def dry_run_problems(settings: dict) -> list[str]:
    problems = []
    if settings.get("dry_run") is False:
        problems.append("dry_run_false")
    trading_mode = settings.get("trading_mode")
    if trading_mode not in (None, "spot"):
        problems.append("trading_mode_not_spot")
    if settings.get("force_entry_enable") is True:
        problems.append("force_entry_enabled")
    exchange = settings.get("exchange") if isinstance(settings.get("exchange"), dict) else {}
    if any(exchange.get(name) for name in ("key", "secret", "password", "uid")):
        problems.append("exchange_credential_present")
    return problems


def assess_host(lock: dict, *, system: str, machine: str, settings: dict | None = None) -> dict:
    host_platform = normalize_platform(system, machine)
    alternate = (lock.get("alternate_platforms") or {}).get("linux/amd64") or {}
    base = {
        "host_system": system,
        "host_machine": machine,
        "host_platform": host_platform,
        "active_compose_platform": lock.get("platform"),
        "active_compose_image": lock.get("image"),
        "recorded_linux_amd64_image": alternate.get("image"),
        "install_performed": False,
        "paid_host_created": False,
    }
    problems = dry_run_problems(settings) if settings is not None else []
    if problems:
        return base | {
            "verdict": "dry_run_contract_failed",
            "problems": problems,
        }
    if host_platform is None:
        return base | {
            "verdict": "not_an_always_on_host",
            "problems": [],
            "note": (
                "systemd units are for a separate always-on Linux host. This Mac and its "
                "Colima VM stop when the laptop sleeps, so they cannot complete the B17 "
                "continuous window. No paid host is created from this check."
            ),
        }
    if host_platform == lock.get("platform"):
        return base | {
            "verdict": "ready_for_dry_run_systemd_install",
            "problems": [],
            "note": "Platform matches the active Compose pin. This check still does not install units.",
        }
    if host_platform == "linux/amd64" and alternate.get("image") and alternate.get("compose_active") is False:
        return base | {
            "verdict": "repoint_compose_to_recorded_amd64_digest_before_install",
            "problems": [],
            "note": (
                "The amd64 digest is recorded and its offline tests passed, but Compose on "
                "this checkout still pins linux/arm64. Repoint VERSION.lock.json and "
                "compose.yaml together, then rerun the container tests on that host before "
                "enabling systemd."
            ),
        }
    return base | {
        "verdict": "platform_unverified",
        "problems": ["no_recorded_image_for_host_platform"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path)
    args = parser.parse_args()
    try:
        with LOCK_PATH.open(encoding="utf-8") as stream:
            lock = read_settings(stream)
        settings = None
        if args.settings is not None:
            with args.settings.open(encoding="utf-8") as stream:
                settings = read_settings(stream)
        report = assess_host(
            lock,
            system=platform.system(),
            machine=platform.machine(),
            settings=settings,
        )
        print(json.dumps(report, indent=2))
        return 0 if report["verdict"] != "dry_run_contract_failed" else 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Host readiness check failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
