"""Milestone 4 acceptance tests for normalized equity accounting and fail-closed entry gating."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest import TestCase, skipIf
from unittest.mock import patch

BOT_DIR = Path(__file__).resolve().parents[1]
for extra in (BOT_DIR / "scripts", BOT_DIR / "risk", BOT_DIR / "strategies"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import guard_runner
import paper_status
from guard import (
    FillEvent,
    FlowEvent,
    Guard,
    reconstruct_fill_stream_snapshot,
    snapshot_from_paper_sqlite,
)

try:
    if sys.version_info < (3, 12):
        raise ImportError("Freqtrade requires Python 3.12+")
    from freqtrade.enums import ExitType
    from freqtrade.persistence import LocalTrade
    from freqtrade.resolvers import StrategyResolver
    from freqtrade.strategy.strategy_wrapper import strategy_safe_wrapper
except ImportError:
    StrategyResolver = None


class GuardAccountingAndMatrixTest(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.state_file = self.root / "guard.state.json"
        self.midnight = datetime(2026, 11, 16, 0, 0, 0, tzinfo=timezone.utc)
        self.guard = Guard(
            self.state_file, "paper:binance:USDT", Decimal("20"), timedelta(seconds=30),
        )

    def test_realized_open_and_base_or_third_currency_fees_trip_at_boundary(self):
        # 1. Buy 1 ETH @ 500 with fee paid in ETH (0.002 ETH) -> holdings = 0.998 ETH, quote = 500 USDT.
        # 2. Buy 2 SOL @ 100 with fee paid in BNB (0.01 BNB @ 600 USDT = 6 USDT) -> quote = 294 USDT.
        # Marks: ETH bid = 490, SOL bid = 95. Exit fee rate = 0.001.
        fills = [
            FillEvent("ord-1", "ETH/USDT", "buy", Decimal("1"), Decimal("500"), Decimal("0.002"), "ETH"),
            FillEvent("ord-2", "SOL/USDT", "buy", Decimal("2"), Decimal("100"), Decimal("0.01"), "BNB"),
        ]
        open_snap = reconstruct_fill_stream_snapshot(
            account="paper:binance:USDT",
            observed_at=self.midnight,
            starting_quote=Decimal("1000"),
            quote_currency="USDT",
            fills=(),
            executable_bid_marks={},
            exit_fee_rate=Decimal("0.001"),
        )
        self.assertIsNone(self.guard.observe(open_snap, self.midnight)["latch"])

        marked_snap = reconstruct_fill_stream_snapshot(
            account="paper:binance:USDT",
            observed_at=self.midnight + timedelta(seconds=10),
            starting_quote=Decimal("1000"),
            quote_currency="USDT",
            fills=fills,
            executable_bid_marks={"ETH/USDT": Decimal("490"), "SOL/USDT": Decimal("95")},
            exit_fee_rate=Decimal("0.001"),
            conversion_marks={"BNB": Decimal("600")},
        )
        # Expected equity = 294 + (0.998*490 + 2*95) * (1 - 0.001) = 294 + 679.02 * 0.999 = 972.34098 -> loss = 27.65902 >= 20
        self.assertTrue(marked_snap.reconciled)
        state = self.guard.observe(marked_snap, self.midnight + timedelta(seconds=10))
        self.assertEqual(state["latch"], "daily_loss")
        self.assertFalse(self.guard.entries_allowed(self.midnight + timedelta(seconds=10)))

        # Missing third-currency conversion mark fails closed.
        unknown_conv = reconstruct_fill_stream_snapshot(
            account="paper:binance:USDT",
            observed_at=self.midnight + timedelta(seconds=15),
            starting_quote=Decimal("1000"),
            quote_currency="USDT",
            fills=fills,
            executable_bid_marks={"ETH/USDT": Decimal("490"), "SOL/USDT": Decimal("95")},
            exit_fee_rate=Decimal("0.001"),
            conversion_marks={},
        )
        self.assertFalse(unknown_conv.reconciled)

    def test_deposits_withdrawals_duplicate_fills_and_unknown_flows(self):
        open_snap = reconstruct_fill_stream_snapshot(
            account="paper:binance:USDT",
            observed_at=self.midnight,
            starting_quote=Decimal("1000"),
            quote_currency="USDT",
            fills=(),
            executable_bid_marks={},
            exit_fee_rate=Decimal("0.001"),
        )
        self.guard.observe(open_snap, self.midnight)

        # Duplicate fill IDs and duplicate flow IDs must be idempotent; withdrawal of 200 USDT must not look like trading loss.
        fill = FillEvent("dup-buy", "BTC/USDT", "buy", Decimal("0.01"), Decimal("5000"), Decimal("0.05"), "USDT")
        withdrawal = FlowEvent("flow-w1", self.midnight + timedelta(seconds=5), Decimal("-200"))
        deposit = FlowEvent("flow-d1", self.midnight + timedelta(seconds=6), Decimal("50"))
        snap = reconstruct_fill_stream_snapshot(
            account="paper:binance:USDT",
            observed_at=self.midnight + timedelta(seconds=10),
            starting_quote=Decimal("1000"),
            quote_currency="USDT",
            fills=[fill, fill],
            executable_bid_marks={"BTC/USDT": Decimal("5000")},
            exit_fee_rate=Decimal("0.001"),
            flow_events=[withdrawal, withdrawal, deposit],
        )
        self.assertTrue(snap.reconciled)
        self.assertEqual(snap.net_flows_today, Decimal("-150"))
        state = self.guard.observe(snap, self.midnight + timedelta(seconds=10))
        self.assertIsNone(state["latch"])
        self.assertTrue(self.guard.entries_allowed(self.midnight + timedelta(seconds=10)))

        # Unknown flow (quote_delta=None) halts entries immediately.
        bad_snap = reconstruct_fill_stream_snapshot(
            account="paper:binance:USDT",
            observed_at=self.midnight + timedelta(seconds=20),
            starting_quote=Decimal("1000"),
            quote_currency="USDT",
            fills=[fill],
            executable_bid_marks={"BTC/USDT": Decimal("5000")},
            exit_fee_rate=Decimal("0.001"),
            flow_events=[FlowEvent("flow-unknown", self.midnight + timedelta(seconds=18), None)],
        )
        self.assertFalse(bad_snap.reconciled)
        state2 = self.guard.observe(bad_snap, self.midnight + timedelta(seconds=20))
        self.assertEqual(state2["latch"], "invalid_or_stale_snapshot")
        self.assertFalse(self.guard.entries_allowed(self.midnight + timedelta(seconds=20)))

    def test_day_rollover_never_clears_prior_breach_and_offline_gap_halts(self):
        open_snap = reconstruct_fill_stream_snapshot(
            account="paper:binance:USDT",
            observed_at=self.midnight,
            starting_quote=Decimal("1000"),
            quote_currency="USDT",
            fills=(),
            executable_bid_marks={},
            exit_fee_rate=Decimal("0.001"),
        )
        self.guard.observe(open_snap, self.midnight)
        breach = reconstruct_fill_stream_snapshot(
            account="paper:binance:USDT",
            observed_at=self.midnight + timedelta(seconds=10),
            starting_quote=Decimal("975"),
            quote_currency="USDT",
            fills=(),
            executable_bid_marks={},
            exit_fee_rate=Decimal("0.001"),
        )
        self.assertEqual(self.guard.observe(breach, self.midnight + timedelta(seconds=10))["latch"], "daily_loss")

        # Next UTC midnight snapshot arrives; prior breach must remain latched across day rollover and reload!
        next_midnight = self.midnight + timedelta(days=1)
        rollover = reconstruct_fill_stream_snapshot(
            account="paper:binance:USDT",
            observed_at=next_midnight,
            starting_quote=Decimal("975"),
            quote_currency="USDT",
            fills=(),
            executable_bid_marks={},
            exit_fee_rate=Decimal("0.001"),
        )
        state_next = self.guard.observe(rollover, next_midnight)
        self.assertEqual(state_next["latch"], "daily_loss")
        reloaded_guard = Guard(
            self.state_file, "paper:binance:USDT", Decimal("20"), timedelta(seconds=30),
        )
        self.assertFalse(reloaded_guard.entries_allowed(next_midnight))

    def test_sqlite_ledger_snapshot_and_api_unavailable_during_breach(self):
        db_file = self.root / "baseline.paper.sqlite"
        with closing(sqlite3.connect(db_file)) as db:
            db.executescript(
                "CREATE TABLE trades ("
                "id INTEGER PRIMARY KEY, pair TEXT, is_open INTEGER, amount REAL, "
                "stake_amount REAL, fee_open_cost REAL, fee_open_currency TEXT, "
                "fee_close REAL, realized_profit REAL, close_profit_abs REAL);"
                "CREATE TABLE orders ("
                "id INTEGER PRIMARY KEY, ft_trade_id INTEGER, ft_pair TEXT, "
                "ft_order_side TEXT, ft_is_open INTEGER, order_id TEXT, status TEXT);"
                "INSERT INTO trades VALUES (1, 'BTC/USDT', 0, 0.0, 50.0, 0.05, 'USDT', 0.001, -12.0, -12.0);"
                "INSERT INTO trades VALUES (2, 'ETH/USDT', 1, 0.5, 50.0, 0.05, 'USDT', 0.001, 0.0, NULL);"
                "INSERT INTO orders VALUES (1, 2, 'ETH/USDT', 'sell', 1, 'protective-exit-1', 'open');"
                "INSERT INTO trades VALUES (3, 'SOL/USDT', 1, 0.0, 50.0, 0.0, 'USDT', 0.001, 0.0, NULL);"
                "INSERT INTO orders VALUES (2, 3, 'SOL/USDT', 'buy', 1, 'pending-buy-3', 'open');"
            )

        policy = {
            "account": "paper:binance:USDT",
            "exchange": "binance",
            "quote_currency": "USDT",
            "starting_wallet_quote": "1000",
            "default_exit_fee_rate": "0.001",
            "max_loss_quote": "20",
            "max_age_seconds": 30.0,
        }
        # Establish opening baseline of 1000 USDT at midnight
        empty_db = self.root / "empty.sqlite"
        snap0 = snapshot_from_paper_sqlite(
            db_path=empty_db,
            account="paper:binance:USDT",
            observed_at=self.midnight,
            starting_wallet=Decimal("1000"),
            quote_currency="USDT",
            executable_bid_marks={},
            default_exit_fee_rate=Decimal("0.001"),
        )
        self.guard.observe(snap0, self.midnight)

        # Poll when ETH bid drops to 70 USDT (0.5 ETH = 35 USDT vs 50 stake -> -15 unrealized, plus -12 closed -> ~ -27 loss >= 20)
        # Simulate API unavailable during breach!
        def broken_api():
            raise RuntimeError("container API unreachable")

        with patch.object(guard_runner, "load_flow_events", return_value=[]):
            now = self.midnight + timedelta(seconds=10)
            snap1 = snapshot_from_paper_sqlite(
                db_path=db_file,
                account="paper:binance:USDT",
                observed_at=now,
                starting_wallet=Decimal("1000"),
                quote_currency="USDT",
                executable_bid_marks={"ETH/USDT": Decimal("70")},
                default_exit_fee_rate=Decimal("0.001"),
            )
            self.guard.observe(snap1, now)
            enforced = guard_runner.enforce_halt(self.guard, now=now, pause_fn=broken_api)

        self.assertEqual(enforced["latch"], "daily_loss")
        self.assertFalse(self.guard.entries_allowed(now))
        self.assertTrue(enforced["enforcement_pending"])
        self.assertIn("trade-3:pending-buy-3", enforced["pending_cancellations"])
        self.assertIn("api_enforcement_deferred", enforced["last_enforcement"]["detail"])

        # Once API recovers, enforcement pauses bot and reconciles pending buy while leaving protective sell intact.
        def recovered_api():
            return {
                "verified_state": "paused",
                "remaining_open_entry_orders": 0,
                "reconciliation": {
                    "cancelled_entry_trade_ids": [3],
                    "preserved_exit_trades": [{"trade_id": 2, "pair": "ETH/USDT", "open_order_sides": ["sell"]}],
                },
            }

        reconciled = guard_runner.enforce_halt(
            self.guard, now=self.midnight + timedelta(seconds=15), pause_fn=recovered_api,
        )
        self.assertFalse(reconciled["enforcement_pending"])
        self.assertEqual(reconciled["pending_cancellations"], [])
        self.assertTrue(reconciled["last_enforcement"]["api_paused"])


@skipIf(StrategyResolver is None, "run in the pinned Freqtrade container")
class GuardedStrategyContainerIntegrationTest(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.userdir = Path(directory.name)
        self.policy_path = self.userdir / "guard.policy.json"
        self.state_path = self.userdir / "guard.state.json"
        self.policy_path.write_text(json.dumps({
            "account": "paper:binance:USDT",
            "max_loss_quote": "20",
            "max_age_seconds": 30,
        }), encoding="utf-8")
        self.strategy = StrategyResolver.load_strategy({
            "strategy": "PersonalSpotGuarded",
            "strategy_path": str(BOT_DIR / "strategies"),
            "user_data_dir": self.userdir,
        })
        self.now = datetime(2026, 11, 16, 0, 0, 10, tzinfo=timezone.utc)

    def _call_wrapped_confirm(self, pair="BTC/USDT", when=None) -> bool:
        # Exercise the exact upstream wrapper (`default_retval=True`) used in FreqtradeBot.execute_entry!
        wrapped = strategy_safe_wrapper(self.strategy.confirm_trade_entry, default_retval=True)
        return wrapped(
            pair=pair,
            order_type="limit",
            amount=0.001,
            rate=50000.0,
            time_in_force="GTC",
            current_time=when or self.now,
            entry_tag="sma_cross_up",
            side="long",
        )

    def test_missing_corrupt_stale_or_exception_states_fail_closed_under_safe_wrapper(self):
        # 1. Missing guard.state.json -> False
        self.assertIs(self._call_wrapped_confirm(), False)

        # 2. Valid armed state -> True (and two simultaneous entry attempts near threshold see identical current permission)
        guard = Guard(self.state_path, "paper:binance:USDT", Decimal("20"), timedelta(seconds=30))
        t0 = datetime(2026, 11, 16, 0, 0, 0, tzinfo=timezone.utc)
        snap0 = reconstruct_fill_stream_snapshot(
            account="paper:binance:USDT", observed_at=t0, starting_quote=Decimal("1000"),
            quote_currency="USDT", fills=(), executable_bid_marks={}, exit_fee_rate=Decimal("0.001"),
        )
        guard.observe(snap0, t0)
        snap_near = reconstruct_fill_stream_snapshot(
            account="paper:binance:USDT", observed_at=self.now, starting_quote=Decimal("981"),
            quote_currency="USDT", fills=(), executable_bid_marks={}, exit_fee_rate=Decimal("0.001"),
        )
        guard.observe(snap_near, self.now)
        self.assertEqual(
            [self._call_wrapped_confirm("BTC/USDT"), self._call_wrapped_confirm("ETH/USDT")],
            [True, True],
        )

        # 3. Stale lease (+31s) and negative clock jump (-5s) -> False
        self.assertIs(self._call_wrapped_confirm(when=self.now + timedelta(seconds=31)), False)
        self.assertIs(self._call_wrapped_confirm(when=self.now - timedelta(seconds=5)), False)

        # 4. Corrupted JSON state -> False (never escapes to default_retval=True)
        self.state_path.write_text("{corrupt-json", encoding="utf-8")
        self.assertIs(self._call_wrapped_confirm(), False)

        # 5. Forced unexpected runtime exception inside _guard_instance -> caught and returns False!
        with patch.object(self.strategy, "_guard_instance", side_effect=RuntimeError("boom")):
            self.assertIs(self._call_wrapped_confirm(), False)

        # 6. Normal exits (signal exit + stoploss) remain completely active while entries are latched/corrupt!
        opened = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
        trade = LocalTrade(
            pair="BTC/USDT", open_rate=100.0, amount=0.5, stake_amount=50.0,
            open_date=opened, fee_open=0.001, fee_close=0.001, is_short=False,
        )
        exits = self.strategy.should_exit(trade, 94.0, self.now, enter=False, exit_=True)
        self.assertEqual([ev.exit_type for ev in exits], [ExitType.EXIT_SIGNAL, ExitType.STOP_LOSS])
