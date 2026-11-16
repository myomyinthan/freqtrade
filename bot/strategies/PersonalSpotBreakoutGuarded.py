"""Paper-guarded H002 strategy: wraps PersonalSpotBreakout with fail-closed entry gating."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys

BOT_DIR = Path(__file__).resolve().parents[1]
for extra in (BOT_DIR / "strategies", BOT_DIR / "risk"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from PersonalSpotBreakout import PersonalSpotBreakout
from guard import Guard

GUARD_POLICY_NAME = "guard.policy.json"
GUARD_STATE_NAME = "guard.state.json"


class PersonalSpotBreakoutGuarded(PersonalSpotBreakout):
    """Wraps PersonalSpotBreakout with a cheap, fail-closed persisted local entry gate."""

    def _guard_instance(self) -> Guard:
        userdir = Path(self.config["user_data_dir"])
        policy_path = userdir / GUARD_POLICY_NAME
        if policy_path.is_symlink():
            raise ValueError("guard policy file must not be a symlink")
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        ratio = policy.get("max_loss_ratio")
        return Guard(
            path=userdir / GUARD_STATE_NAME,
            account=str(policy["account"]),
            max_loss=Decimal(str(policy["max_loss_quote"])),
            max_age=timedelta(seconds=float(policy["max_age_seconds"])),
            max_loss_ratio=Decimal(str(ratio)) if ratio is not None else None,
        )

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag: str | None,
                            side: str, **kwargs) -> bool:
        try:
            now = current_time if isinstance(current_time, datetime) else datetime.now(timezone.utc)
            if now.utcoffset() is None:
                now = now.replace(tzinfo=timezone.utc)
            return bool(self._guard_instance().entries_allowed(now))
        except BaseException:
            return False
