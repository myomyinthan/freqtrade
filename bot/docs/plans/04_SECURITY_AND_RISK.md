# Security, exposure and risk-control design

## Configuration and secrets

All initial launch paths must require resolved `dry_run=true` and `trading_mode=spot`, reject force-entry, and use the dedicated paper DB. Validate effective settings after file merges, command-line options and environment overrides; checking only an example JSON file is insufficient. Fail on unresolved venue/quote placeholders and invalid stake constraints. Store a sanitized effective-config hash with every run.

Use public market-data access for research/paper trading wherever supported. Do not request trading keys merely to make dry-run setup look complete. If a chosen venue requires authenticated read access, document the requirement and use the narrowest account permission. Future live keys belong in ignored files or a secret manager, with no withdrawals, restricted IPs where available, separate accounts/subaccounts where appropriate, and user-managed rotation. Never paste keys into chat, commit them, bake them into images, print environment dumps, or publish unsanitized reports.

Keep the API/UI disabled until needed, then bind the host port to loopback with unique credentials and empty/unneeded CORS disabled. Use SSH tunneling or a private VPN for future remote access. The API can control the bot and should not be exposed publicly. [Freqtrade REST API security](https://www.freqtrade.io/en/stable/rest-api/#security).

Paper and future live environments require distinct DBs, credentials, guard state and configuration; one explicit mode per process. No default live Compose profile. A future live runner should require a reviewed live configuration and a recorded authorization reference rather than allowing a single accidental environment override to switch the paper runner into live mode.

## Exchange capability review

Before the first venue-specific pilot, verify current official exchange documentation and the pinned Freqtrade adapter. Record evidence and review date for spot availability, account/jurisdiction access, symbol names, supported order/time-in-force types, order minimum/maximum sizes, precision and rounding, stoploss-on-exchange support, fee tier/fee currency, OHLCV depth and gaps, rate limits, time synchronization, maintenance behavior and API permissions. Supported features vary by venue. [Freqtrade exchange-specific notes](https://www.freqtrade.io/en/stable/exchanges/).

Test dust/minimum-notional handling, partial fills, cancellation acknowledgements, rejected orders, rate limiting, timeouts with unknown order state, restart reconciliation, and a pair becoming unavailable. After a timeout, query the order state before retrying to avoid duplicates. Paper fills cannot prove a venue's real matching or stop behavior; retain a separate live-verification checklist for a later approved rollout.

Choose order policy only after this review. Do not assert that stop orders are available everywhere. An on-exchange stop may provide protection during bot downtime but can have type/support and execution constraints; an off-exchange stop depends on bot connectivity and uptime. Gaps and stop-limit nonfills remain possible. [Freqtrade stoploss modes](https://www.freqtrade.io/en/stable/stoploss/).

## Exposure budget

The baseline uses paper fixtures only. Before any live proposal, record the owner's maximum allocated capital, maximum position stake, concurrent positions, quote reserve, total open exposure, per-trade risk target, daily entry-halt threshold, overall drawdown threshold, and acceptable slippage/spread. Explain units: quote-currency amount versus fraction of start-of-day equity. Never turn an unfilled exchange minimum into permission to raise stake beyond the approved limit.

Correlated assets can lose together. Limit total open exposure as well as per-position stake, include pending buy orders in reserved exposure, and account for fee reserves. A strategy stop is an exit trigger, not a guaranteed maximum loss. Manual exchange activity or a second bot invalidates a single-bot accounting assumption; isolate the deployment or widen the accounting scope explicitly.

## Built-in protection boundary

CooldownPeriod and StoplossGuard are useful local controls, but they do not establish a hard account-wide calendar-day loss limit. Native protections alone should not be presented as including every open mark-to-market loss, unrelated account activity, transfer or pending order. Historical protection tests also do not validate an external guard. [Freqtrade protection semantics](https://www.freqtrade.io/en/stable/plugins/#protections).

## Proposed persisted daily guard

Implement this after the basic paper pipeline. It is required before claiming daily-loss enforcement or considering a live pilot. Its supported action is a **latched halt of new entries**, with pending entry cancellation and continued normal exit handling. It never automatically liquidates positions. A polling guard cannot guarantee that monetary losses stay below a threshold because positions remain exposed, fills can race, prices can gap and services can fail.

### Accounting contract

Use a dedicated account/subaccount or explicitly scoped paper wallet. In quote units define:

`E(t) = total quote balance + sum(total base quantity × conservative executable mark) - estimated uncharged exit costs`

Total balances include free and reserved assets exactly once. In paper mode reconstruct the same economic quantities from the dry-run wallet and trade/order ledger; do not read the real exchange balance and call it paper equity. Reconcile fills and fee currencies without double-counting fees already reflected in balances. Prefer fresh bid-side executable marks and flag unknown conversion prices. Exclude non-bot holdings only when the isolated scope and ownership are unambiguous.

At UTC day start persist reconciled equity `E0`. Let `F(t)` be cumulative net external contributions since that snapshot, positive for deposits and negative for withdrawals, valued at event time. Daily P&L is `P(t) = E(t) - E0 - F(t)`; daily loss fraction is `max(0, -P(t)) / E0`. Halt at the configured absolute or relative loss threshold. Separately define lifetime/rolling peak drawdown if required; it is not interchangeable with daily P&L.

Use UTC for boundaries regardless of display timezone or daylight saving. Carried positions remain included in opening equity; their subsequent change counts that day. Unknown deposits/withdrawals, stale marks, invalid equity or an unreconciled ledger produce an entry halt, not a fabricated zero loss. If the process was offline at midnight and a trustworthy boundary snapshot cannot be reconstructed, halt and require reconciliation; do not quietly reset the baseline to current equity.

### State and enforcement

Persist schema version, bot/account/mode identity, UTC day, opening equity, latest reconciled equity/flows, last successful poll time, threshold settings/hash, latch reason/time, processed fill/order IDs, pending cancellations and manual reset audit. Write atomically to a separate guard database/state file; never modify the trading DB directly. Retain state through restart and corruption recovery; absence or unreadable state denies new entry permission.

Proposed paper timing: poll every 10 seconds; entry permission expires after 30 seconds without a valid snapshot. These are measurable design targets to validate against venue rate limits, not guaranteed response times. Include polling, rate-limit backoff, API latency and order-submission races in the measured detection/enforcement bound. Clock skew must be detected; use a monotonic freshness check within a process and validate persisted UTC timestamps after restart.

When loss threshold, stale data, ledger mismatch or operator halt occurs:

1. Atomically latch `entries_allowed=false` with a reason before relying on the trading API.
2. Strategy entry confirmation reads permission with a cheap, bounded local check and denies new entries on stale/missing/latched state. Keep force-entry and position adjustment disabled. Catch state, I/O, parse, identity and timing errors inside the callback and explicitly return `False`; do not allow guard errors to escape into an upstream wrapper that may approve by default. The inspected stable engine wraps `confirm_trade_entry` with `default_retval=True`; verify the pinned source and integration-test the engine exception path, not only the guard helper. Unexpected callback exceptions must be treated as an unresolved fail-open risk until contained. [Freqtrade engine source](https://github.com/freqtrade/freqtrade/blob/stable/freqtrade/freqtradebot.py).
3. Invoke the pinned version's verified API operation that pauses new entries while keeping exits managed; current documentation describes `/stopbuy` and `/pause`. Verify actual selected-release behavior, then record one supported operation in the implementation. [Freqtrade API endpoints](https://www.freqtrade.io/en/stable/rest-api/#available-endpoints).
4. Enumerate and cancel only outstanding **entry** orders. Preserve exit and protective-stop orders. Re-query until each entry order is canceled, rejected or filled; handle partial fills as positions, track residual quantities and alert on unknown states. Never claim a cancel request proves no fill.
5. Keep checking and managing normal exits, retain the latch across restart/reload, and emit a local incident alert. A persisted gate remains authoritative even if a reload clears an upstream in-memory pause.

New-day rollover does not automatically clear a prior breach. Operator rearm requires reconciled equity/orders, a fresh heartbeat, a recorded reason and deliberate action. Changing the date, restarting the service, or editing the threshold must not silently remove the latch. Dry-run test fixtures can simulate rearm; real-money rearm later needs the operator's agreed procedure.

### Acceptance tests

| Scenario | Required result |
| --- | --- |
| Realized loss, open-position loss, fee paid in base/third currency | One coherent equity result; threshold trips at the expected boundary. |
| Deposit, withdrawal, duplicate fill/event | Flows excluded from P&L; duplicates idempotent; unknown flows halt. |
| Day rollover with open positions or offline gap | Correct opening snapshot, or halt for reconciliation. |
| Guard process killed, stale quote, corrupted state, clock jump | Entry confirmation denies; normal exits are not intentionally disabled. |
| Breach with pending buy and protective sell | Cancel buy only; re-query fills; preserve protective exit. |
| Restart/reload after breach | Latch and unresolved cancellation state survive; no fresh entries. |
| API unavailable during breach | Local entry gate remains denied; incident visible; reconcile API action later. |
| Two simultaneous entry attempts near threshold | Both use current permission; any residual race documented and exposure bounded. |

Test the policy on synthetic ledger streams and through paper integration. A backtest lacking intrabar equity polling cannot demonstrate this guard's effectiveness; report guard-free historical results separately from guard-replay experiments.
