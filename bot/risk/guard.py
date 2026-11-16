"""Persist an entry-halt policy for a reconciled paper-account snapshot feed."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from collections import defaultdict
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import fcntl


@dataclass(frozen=True)
class Snapshot:
    account: str
    observed_at: datetime
    equity: Decimal
    net_flows_today: Decimal
    reconciled: bool
    pending_entries: tuple[str, ...] = ()
    processed_order_ids: tuple[str, ...] = ()
    processed_flow_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class FlowEvent:
    event_id: str
    timestamp: datetime
    quote_delta: Decimal | None


@dataclass(frozen=True)
class FillEvent:
    order_id: str
    pair: str
    side: str
    filled: Decimal
    price: Decimal
    fee_amount: Decimal = Decimal("0")
    fee_currency: str | None = None
    is_open: bool = False
    remaining_stake_reserved: Decimal = Decimal("0")


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def paper_equity(quote_balance, holdings, uncharged_exit_cost):
    """Holdings contain total quantities and fresh executable marks, once per asset."""
    items = tuple(holdings)
    values = (quote_balance, uncharged_exit_cost, *(v for item in items for v in item))
    if any(not value.is_finite() or value < 0 for value in values):
        raise ValueError("paper equity needs valid nonnegative balances, marks and costs")
    if any(quantity > 0 and mark == 0 for quantity, mark in items):
        raise ValueError("an open holding is missing an executable mark")
    return quote_balance + sum(quantity * mark for quantity, mark in items) - uncharged_exit_cost


def sum_daily_flows(events, utc_day: str) -> tuple[Decimal, bool, tuple[str, ...]]:
    """Aggregate idempotent external flows for `utc_day`; halt (`reconciled=False`) on unknown flows."""
    seen: set[str] = set()
    net = Decimal("0")
    for event in events:
        if not event.event_id:
            return Decimal("0"), False, tuple(sorted(seen))
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        if event.timestamp.utcoffset() is None:
            return Decimal("0"), False, tuple(sorted(seen))
        if event.timestamp.astimezone(timezone.utc).date().isoformat() != utc_day:
            continue
        if event.quote_delta is None or not event.quote_delta.is_finite():
            return Decimal("0"), False, tuple(sorted(seen))
        net += event.quote_delta
    return net, True, tuple(sorted(seen))


def reconstruct_fill_stream_snapshot(
    *,
    account: str,
    observed_at: datetime,
    starting_quote: Decimal,
    quote_currency: str,
    fills,
    executable_bid_marks: dict[str, Decimal],
    exit_fee_rate: Decimal,
    conversion_marks: dict[str, Decimal] | None = None,
    flow_events=(),
) -> Snapshot:
    """Reconstruct normalized spot paper equity from an idempotent stream of fills, fees and external flows."""
    utc_day = observed_at.astimezone(timezone.utc).date().isoformat()
    net_flows, flows_ok, flow_ids = sum_daily_flows(flow_events, utc_day)
    conversions = conversion_marks or {}
    quote = _dec(starting_quote) + net_flows
    base_holdings: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    seen_orders: set[str] = set()
    pending_entries: list[str] = []
    reconciled = flows_ok and exit_fee_rate.is_finite() and exit_fee_rate >= 0

    for fill in fills:
        if not fill.order_id:
            reconciled = False
            continue
        if fill.order_id in seen_orders:
            continue
        seen_orders.add(fill.order_id)
        base, sep, pair_quote = fill.pair.partition("/")
        if not sep or pair_quote != quote_currency:
            reconciled = False
            continue
        if fill.is_open and fill.side == "buy":
            pending_entries.append(fill.order_id)

        if fill.filled < 0 or fill.price <= 0 or fill.fee_amount < 0:
            reconciled = False
            continue

        gross_quote = fill.filled * fill.price
        fee_ccy = fill.fee_currency or quote_currency
        if fill.side == "buy":
            quote -= gross_quote
            base_holdings[base] += fill.filled
            if fee_ccy == base:
                # Base-denominated entry fee reduces received base asset; do not deduct from quote again.
                base_holdings[base] -= fill.fee_amount
            elif fee_ccy == quote_currency:
                quote -= fill.fee_amount
            else:
                conv = conversions.get(fee_ccy)
                if conv is None or not conv.is_finite() or conv <= 0:
                    reconciled = False
                else:
                    quote -= fill.fee_amount * conv
        elif fill.side == "sell":
            quote += gross_quote
            base_holdings[base] -= fill.filled
            if fee_ccy == quote_currency:
                quote -= fill.fee_amount
            elif fee_ccy == base:
                base_holdings[base] -= fill.fee_amount
            else:
                conv = conversions.get(fee_ccy)
                if conv is None or not conv.is_finite() or conv <= 0:
                    reconciled = False
                else:
                    quote -= fill.fee_amount * conv
        else:
            reconciled = False

    holdings_marks: list[tuple[Decimal, Decimal]] = []
    uncharged_exit_cost = Decimal("0")
    for asset, qty in sorted(base_holdings.items()):
        if qty < 0:
            reconciled = False
            continue
        if qty == 0:
            continue
        pair = f"{asset}/{quote_currency}"
        mark = executable_bid_marks.get(pair)
        if mark is None or not mark.is_finite() or mark <= 0:
            reconciled = False
            holdings_marks.append((qty, Decimal("0")))
        else:
            holdings_marks.append((qty, mark))
            uncharged_exit_cost += qty * mark * exit_fee_rate

    if quote < 0 or not reconciled:
        return Snapshot(
            account=account,
            observed_at=observed_at,
            equity=Decimal("0"),
            net_flows_today=net_flows,
            reconciled=False,
            pending_entries=tuple(sorted(set(pending_entries))),
            processed_order_ids=tuple(sorted(seen_orders)),
            processed_flow_ids=flow_ids,
        )

    equity = paper_equity(quote, holdings_marks, uncharged_exit_cost)
    return Snapshot(
        account=account,
        observed_at=observed_at,
        equity=equity,
        net_flows_today=net_flows,
        reconciled=True,
        pending_entries=tuple(sorted(set(pending_entries))),
        processed_order_ids=tuple(sorted(seen_orders)),
        processed_flow_ids=flow_ids,
    )


def snapshot_from_paper_sqlite(
    *,
    db_path: Path,
    account: str,
    observed_at: datetime,
    starting_wallet: Decimal,
    quote_currency: str,
    executable_bid_marks: dict[str, Decimal],
    default_exit_fee_rate: Decimal,
    flow_events=(),
) -> Snapshot:
    """Reconstruct dry-run paper equity directly from Freqtrade's SQLite ledger and fresh bid marks."""
    utc_day = observed_at.astimezone(timezone.utc).date().isoformat()
    net_flows, flows_ok, flow_ids = sum_daily_flows(flow_events, utc_day)
    if not db_path.is_file():
        if not flows_ok or starting_wallet + net_flows <= 0:
            return Snapshot(account, observed_at, Decimal("0"), net_flows, False, (), (), flow_ids)
        return Snapshot(
            account=account,
            observed_at=observed_at,
            equity=starting_wallet + net_flows,
            net_flows_today=net_flows,
            reconciled=True,
            pending_entries=(),
            processed_order_ids=(),
            processed_flow_ids=flow_ids,
        )

    uri = db_path.absolute().as_uri()
    try:
        conn = sqlite3.connect(uri + "?mode=ro", uri=True)
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
    except sqlite3.OperationalError:
        wal = Path(str(db_path) + "-wal")
        if wal.exists() and wal.stat().st_size > 0:
            return Snapshot(account, observed_at, Decimal("0"), net_flows, False, (), (), flow_ids)
        conn = sqlite3.connect(uri + "?mode=ro&immutable=1", uri=True)

    with closing(conn) as db:
        closed_profit_raw = db.execute(
            "SELECT COALESCE(SUM(close_profit_abs), 0.0) FROM trades WHERE NOT is_open"
        ).fetchone()[0]
        open_rows = db.execute(
            "SELECT id, pair, amount, stake_amount, fee_open_cost, fee_open_currency, "
            "fee_close, realized_profit FROM trades WHERE is_open"
        ).fetchall()
        order_rows = db.execute(
            "SELECT id, ft_trade_id, ft_pair, ft_order_side, ft_is_open, order_id, status "
            "FROM orders"
        ).fetchall()

    processed_orders = tuple(
        sorted({str(row[5] or f"local-{row[0]}") for row in order_rows})
    )
    pending_entries = tuple(
        sorted({
            f"trade-{row[1]}:{row[5] or row[0]}"
            for row in order_rows
            if row[4] and row[3] == "buy"
        })
    )
    if not flows_ok:
        return Snapshot(
            account, observed_at, Decimal("0"), net_flows, False,
            pending_entries, processed_orders, flow_ids,
        )

    closed_profit = _dec(closed_profit_raw or 0)
    open_partial_realized = Decimal("0")
    committed_quote = Decimal("0")
    holdings_by_pair: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    uncharged_exit_cost = Decimal("0")

    for trade_id, pair, amount, stake_amt, fee_open_cost, fee_open_ccy, fee_close, realized_prof in open_rows:
        amt = _dec(amount or 0)
        stake = _dec(stake_amt or 0)
        open_fee_cost = _dec(fee_open_cost or 0)
        open_partial_realized += _dec(realized_prof or 0)
        committed_quote += stake
        # Freqtrade deducts quote entry fee at trade close if not already taken out of base amount;
        # include quote-denominated open fee once when stake has not already absorbed it.
        if (fee_open_ccy in (None, "", quote_currency)) and amt > 0 and open_fee_cost > 0:
            committed_quote += open_fee_cost
        elif fee_open_ccy not in (None, "", quote_currency, pair.partition("/")[0]):
            return Snapshot(
                account, observed_at, Decimal("0"), net_flows, False,
                pending_entries, processed_orders, flow_ids,
            )
        if amt > 0:
            holdings_by_pair[pair] += amt
            close_rate = _dec(fee_close) if fee_close is not None else default_exit_fee_rate
            mark = executable_bid_marks.get(pair)
            if mark is None or not mark.is_finite() or mark <= 0 or close_rate < 0:
                return Snapshot(
                    account, observed_at, Decimal("0"), net_flows, False,
                    pending_entries, processed_orders, flow_ids,
                )
            uncharged_exit_cost += amt * mark * close_rate

    quote_balance = starting_wallet + net_flows + closed_profit + open_partial_realized - committed_quote
    if quote_balance < 0:
        return Snapshot(
            account, observed_at, Decimal("0"), net_flows, False,
            pending_entries, processed_orders, flow_ids,
        )

    holdings_marks = [
        (qty, executable_bid_marks[pair])
        for pair, qty in sorted(holdings_by_pair.items())
        if qty > 0
    ]
    equity = paper_equity(quote_balance, holdings_marks, uncharged_exit_cost)
    return Snapshot(
        account=account,
        observed_at=observed_at,
        equity=equity,
        net_flows_today=net_flows,
        reconciled=True,
        pending_entries=pending_entries,
        processed_order_ids=processed_orders,
        processed_flow_ids=flow_ids,
    )


class Guard:
    def __init__(
        self,
        path: Path,
        account: str,
        max_loss: Decimal,
        max_age: timedelta,
        max_loss_ratio: Decimal | None = None,
    ):
        if not account or not max_loss.is_finite() or max_loss <= 0 or max_age <= timedelta():
            raise ValueError("configure a paper account, positive daily loss and heartbeat limit")
        if max_loss_ratio is not None and (not max_loss_ratio.is_finite() or not Decimal(0) < max_loss_ratio < Decimal(1)):
            raise ValueError("max_loss_ratio must be a finite fraction between 0 and 1")
        self.path = path
        self.account = account
        self.max_loss = max_loss
        self.max_age = max_age
        self.max_loss_ratio = max_loss_ratio
        self.threshold_sha256 = hashlib.sha256(
            json.dumps(
                {
                    "account": self.account,
                    "mode": "paper",
                    "max_loss": str(self.max_loss),
                    "max_loss_ratio": str(self.max_loss_ratio) if self.max_loss_ratio is not None else None,
                    "max_age_seconds": self.max_age.total_seconds(),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    def _read(self):
        if self.path.is_symlink():
            raise ValueError("guard state path must not be a symlink")
        with self.path.open(encoding="utf-8") as stream:
            state = json.load(stream)
        if (
            state["version"] != 1 or state["account"] != self.account or state["mode"] != "paper"
            or Decimal(state["max_loss"]) != self.max_loss
            or state.get("max_loss_ratio") != (str(self.max_loss_ratio) if self.max_loss_ratio is not None else None)
        ):
            raise ValueError("guard state does not match this paper account or threshold")
        return state

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def _save(self, state):
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=self.path.parent, delete=False,
        ) as stream:
            temp = Path(stream.name)
            try:
                os.chmod(temp, 0o600)
                json.dump(state, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(temp, self.path)
            finally:
                temp.unlink(missing_ok=True)
        descriptor = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _within_loss_limits(self, loss: Decimal, opening: Decimal) -> bool:
        if not loss.is_finite() or loss >= self.max_loss:
            return False
        if self.max_loss_ratio is not None:
            if not opening.is_finite() or opening <= 0:
                return False
            if (loss / opening) >= self.max_loss_ratio:
                return False
        return True

    def entries_allowed(self, now: datetime) -> bool:
        try:
            state = self._read()
            observed = datetime.fromisoformat(state["last_observed_at"])
            if state["latch"] is not None or state["loss"] is None or state.get("opening_equity") is None:
                return False
            loss = Decimal(state["loss"])
            opening = Decimal(state["opening_equity"])
            return (
                self._within_loss_limits(loss, opening)
                and state["utc_day"] == now.astimezone(timezone.utc).date().isoformat()
                and timedelta() <= now - observed <= self.max_age
            )
        except Exception:
            # Keep storage, identity, clock and parsing errors inside the entry callback's decision boundary.
            return False

    def _empty_state(self) -> dict:
        return {
            "version": 1,
            "mode": "paper",
            "account": self.account,
            "max_loss": str(self.max_loss),
            "max_loss_ratio": str(self.max_loss_ratio) if self.max_loss_ratio is not None else None,
            "threshold_sha256": self.threshold_sha256,
            "utc_day": None,
            "latch": None,
            "latched_at": None,
            "opening_equity": None,
            "latest_equity": None,
            "net_flows_today": None,
            "loss": None,
            "loss_ratio": None,
            "pending_entries": [],
            "pending_cancellations": [],
            "processed_order_ids": [],
            "processed_flow_ids": [],
            "enforcement_pending": False,
            "last_enforcement": None,
            "rearm_audit": [],
        }

    def observe(self, snapshot: Snapshot, now: datetime):
        if snapshot.account != self.account or snapshot.observed_at.utcoffset() is None:
            raise ValueError("snapshot requires the matching paper account and an aware timestamp")
        observed = snapshot.observed_at.astimezone(timezone.utc)
        age = now - observed
        day = observed.date().isoformat()
        opening_snapshot = observed == observed.replace(hour=0, minute=0, second=0, microsecond=0)
        valid = (
            timedelta() <= age <= self.max_age and snapshot.reconciled
            and snapshot.equity.is_finite() and snapshot.equity > 0
            and snapshot.net_flows_today.is_finite()
        )
        with self._locked():
            try:
                state = self._read()
                last = datetime.fromisoformat(state["last_observed_at"])
                if observed <= last:
                    raise ValueError("paper snapshots must be strictly chronological")
            except FileNotFoundError:
                state = self._empty_state()
                last = None

            prior_latch = state["latch"]
            if not valid:
                state["latch"] = state["latch"] or "invalid_or_stale_snapshot"
            if last is not None and observed - last > self.max_age:
                state["latch"] = state["latch"] or "heartbeat_gap"
            if state["utc_day"] != day:
                if opening_snapshot and valid and snapshot.net_flows_today == 0:
                    state["opening_equity"] = str(snapshot.equity)
                else:
                    state["opening_equity"] = None
                    state["latch"] = state["latch"] or "missing_utc_opening_equity"

            loss = None
            loss_ratio = None
            if valid and state["opening_equity"] is not None:
                opening = Decimal(state["opening_equity"])
                loss = max(Decimal(0), opening + snapshot.net_flows_today - snapshot.equity)
                loss_ratio = (loss / opening) if opening > 0 else None
                if not self._within_loss_limits(loss, opening):
                    state["latch"] = state["latch"] or "daily_loss"

            merged_orders = sorted(
                set(state.get("processed_order_ids", ())) | set(snapshot.processed_order_ids)
            )[-500:]
            merged_flows = sorted(
                set(state.get("processed_flow_ids", ())) | set(snapshot.processed_flow_ids)
            )[-200:]
            pending = sorted(set(snapshot.pending_entries))
            if state["latch"] is not None and prior_latch is None:
                state["latched_at"] = now.astimezone(timezone.utc).isoformat()
                state["enforcement_pending"] = True
                state["pending_cancellations"] = list(pending)
            elif state["latch"] is not None and pending:
                # Track any newly observed pending entries while latched until API cancellation succeeds.
                state["pending_cancellations"] = sorted(
                    set(state.get("pending_cancellations", ())) | set(pending)
                )
                state["enforcement_pending"] = True

            state.update(
                threshold_sha256=self.threshold_sha256,
                utc_day=day,
                last_observed_at=observed.isoformat(),
                latest_equity=str(snapshot.equity) if valid else None,
                net_flows_today=str(snapshot.net_flows_today) if valid else None,
                loss=str(loss) if loss is not None else None,
                loss_ratio=str(loss_ratio) if loss_ratio is not None else None,
                pending_entries=pending,
                processed_order_ids=merged_orders,
                processed_flow_ids=merged_flows,
            )
            self._save(state)
            return state

    def latch_manual(self, now: datetime, reason: str):
        if not reason.strip():
            raise ValueError("manual halt requires a reason")
        with self._locked():
            try:
                state = self._read()
            except FileNotFoundError:
                state = self._empty_state()
                state["utc_day"] = now.astimezone(timezone.utc).date().isoformat()
                state["last_observed_at"] = now.astimezone(timezone.utc).isoformat()
            if state["latch"] is None:
                state["latch"] = f"operator_halt:{reason.strip()}"
                state["latched_at"] = now.astimezone(timezone.utc).isoformat()
            state["enforcement_pending"] = True
            self._save(state)
            return state

    def record_enforcement(
        self,
        now: datetime,
        *,
        api_paused: bool,
        remaining_pending_entries: tuple[str, ...],
        detail: str,
        latency_ms: float | None = None,
    ):
        with self._locked():
            state = self._read()
            remaining = sorted(set(remaining_pending_entries))
            state["pending_cancellations"] = remaining
            state["enforcement_pending"] = bool(not api_paused or remaining)
            state["last_enforcement"] = {
                "timestamp": now.astimezone(timezone.utc).isoformat(),
                "api_paused": bool(api_paused),
                "remaining_pending_entries": remaining,
                "detail": detail,
                "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
            }
            self._save(state)
            return state

    def bootstrap_day_baseline(self, snapshot: Snapshot, now: datetime, reason: str):
        """Explicit operator baseline registration when starting mid-UTC-day after reconciliation."""
        if not reason.strip():
            raise ValueError("baseline registration requires an operator reason")
        state = self.observe(snapshot, now)
        with self._locked():
            state = self._read()
            if state["latch"] != "missing_utc_opening_equity":
                raise ValueError(
                    f"day baseline bootstrap applies only to missing_utc_opening_equity, got {state['latch']!r}"
                )
            if state["pending_entries"] or state.get("latest_equity") is None:
                raise ValueError("day baseline bootstrap requires reconciled equity and no pending entries")
            state["opening_equity"] = state["latest_equity"]
            state["loss"] = "0"
            state["loss_ratio"] = "0"
            state["rearm_audit"].append({
                "timestamp": now.astimezone(timezone.utc).isoformat(),
                "reason": reason.strip(),
                "prior_latch": state["latch"],
                "registered_opening_equity": state["opening_equity"],
            })
            state["latch"] = None
            state["latched_at"] = None
            state["enforcement_pending"] = False
            state["pending_cancellations"] = []
            self._save(state)
            return state

    def rearm(self, now: datetime, reason: str):
        if not reason.strip():
            raise ValueError("rearm requires an operator reason")
        with self._locked():
            state = self._read()
            if state["latch"] is None:
                raise ValueError("guard is already armed")
            observed = datetime.fromisoformat(state["last_observed_at"])
            has_fresh_heartbeat = (
                state["utc_day"] == now.astimezone(timezone.utc).date().isoformat()
                and timedelta() <= now - observed <= self.max_age
            )
            if not has_fresh_heartbeat or state["pending_entries"]:
                raise ValueError(
                    "rearm requires fresh reconciled equity below the limit and no pending entries"
                )
            if state["loss"] is None and state.get("opening_equity") is None:
                if state["latch"] != "missing_utc_opening_equity":
                    raise ValueError(
                        "rearm requires fresh reconciled equity below the limit and no pending entries"
                    )
                if state.get("latest_equity") is not None:
                    state["opening_equity"] = state["latest_equity"]
                    state["loss"] = "0"
                    state["loss_ratio"] = "0"
            else:
                if (
                    state["loss"] is None or state.get("opening_equity") is None
                    or not self._within_loss_limits(Decimal(state["loss"]), Decimal(state["opening_equity"]))
                ):
                    raise ValueError(
                        "rearm requires fresh reconciled equity below the limit and no pending entries"
                    )
            state["rearm_audit"].append({
                "timestamp": now.isoformat(), "reason": reason, "prior_latch": state["latch"],
            })
            state["latch"] = None
            state["latched_at"] = None
            state["enforcement_pending"] = False
            state["pending_cancellations"] = []
            self._save(state)
