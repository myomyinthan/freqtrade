# Executable backlog and stage gates

Each row should become a small commit or PR with its acceptance evidence attached. Implement sequentially where dependencies require it. Parallel agents are unnecessary. Sol should start with **M0 only**, report the reviewable result, then continue when instructed; this planning request does not itself authorize implementation.

## M0 — Fork and safe project skeleton

| ID | Task | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| B01 | Read plans/readiness; inspect current files, remotes, tools and policy files. Verify GitHub owner and existing fork. | None | Findings distinguish observed failures from inferred causes; no token values logged; unresolved owner/network issues explicitly recorded. |
| B02 | Resolve a released stable tag and full source SHA; identify a compatible pinned runtime/image digest and platform. | B01 | Lockfile fields verified from source/runtime; no guessed latest tag or mutable-only pin. If runtime unavailable, status remains unverified rather than passed. |
| B03 | Create/reuse the personal fork and safely clone into a new `freqtrade/` child; create project branch from B02. | B01, B02 | `origin` is owned fork; `upstream` is official; selected base SHA matches; existing planning artifacts preserved. If GitHub blocked, leave this pending and continue independent local template work. |
| B04 | Add `bot/` layout, plans, ignores, runtime mounts and credential-free example config. | B03 for final integration | Example files tracked, generated data/secrets ignored, no core engine edits; dry-run default and spot mode visible. |
| B05 | Implement preflight and safe paper runner. Validate merged configuration, relevant environment overrides, exchange placeholder checks and DB paths. Defer real baseline strategy loading to B06. | B04 | A malicious/test override to `dry_run=false` is rejected; futures mode, force-entry, shared DB and missing exchange/quote fail closed. If a load fixture is needed, use an explicitly inert no-entry strategy. No test places an order. |

**M0 handoff:** changed files, verified version references, tests actually run, blockers and required user decisions. Do not claim a runnable exchange pilot while exchange/quote/engine prerequisites are unresolved. Installing system dependencies or authenticating accounts must follow available authorization; do not replace the user's system Python.

## M1 — Baseline behavior and data contract

| ID | Task | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| B06 | Implement `PersonalSpotBaseline` exactly as the registered hypothesis; add deterministic behavioral fixtures. | B04 | Entry/exit crossing, equality, warmup, missing volume, and prefix-invariance tests pass; no shorts or DCA. |
| B07 | Resolve exchange, quote, pairs and paper wallet with user; write capability matrix from official venue and pinned Freqtrade sources. | B01 | Pair format, spot support, region/account access, fee assumptions, precision/minimums, stop/order support, rate limits and history availability recorded; no venue guessed. |
| B08 | Implement download wrapper and data audit; freeze a dataset manifest and chronological evaluation protocol. | B02, B07 | UTC contiguous timestamps, duplicates/gaps/incomplete candles assessed; checksums recorded; warmup available; split dates locked before results. |
| B09 | Add project CI for strategy/config tests, secret detection and manifest/schema validation. | B05, B06 | CI requires no exchange credentials; jobs use pinned runtime; default workflow cannot launch live trading or spend infrastructure budget. |

**M1 gate:** no dangerous configuration can launch through the paper runner, strategy behavior is reproducible, and historical data has documented coverage. Missing data is a visible limitation, not silently forward-filled price action.

## M2 — Historical evaluation and bias review

| ID | Task | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| B10 | Execute frozen training and validation runs with protections enabled and full provenance. | B06, B08 | Fresh-cache artifacts include per-pair/per-period results, open-at-end handling, benchmark, fee settings and all attempted variants. |
| B11 | Run lookahead and recursive analyses; test calculations on truncated prefixes. | B10 | All intended entry/exit branches actually exercised; no-trade or omitted-signal cases marked inconclusive; startup requirements established. |
| B12 | Add fee/slippage stress, chronological walk-forward and pair/regime concentration checks. | B10, B11 | Costs and stress model explicit; repeat runs agree; no sensitivity threshold selected after viewing the untouched test. |
| B13 | Freeze candidate and evaluate untouched test exactly once; write pass/fail/inconclusive report. | B12 | Report preserves disappointing outcomes; compares gates from protocol; no test-period retuning. |

**M2 gate:** research is reproducible and unbiased to the extent tested. A failed economic hypothesis may advance to a paper-only engineering exercise with that label, but never to a live recommendation. An inconclusive result cannot pass an evidence gate.

## M3 — Paper-trading operation

| ID | Task | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| B14 | Run a short local paper smoke with a fresh dedicated DB, fixed config and no trading credentials. | B05–B09 | Resolved `dry_run=true`; correct spot pairs; strategy loaded; candles fresh; local API authenticated if enabled. No order sent to exchange. |
| B15 | Implement status reporting and local alerts; retain logs/results with rotation and sanitized exports. | B14 | Detect stale feed, failed heartbeat, repeated errors, disk pressure, and restart; external notification destination requires user choice. |
| B16 | Drill restart, network outage, manual entry pause, pending-entry reconciliation, backup and isolated restore. | B14, B15 | Existing paper trades preserved; no duplicate writers; pause/stop distinction and recovery verified; restore does not alter production state. |
| B17 | Run monitored paper pilot with frozen candidate/config; compare observed paper execution with historical assumptions. | B13–B16 | At least 30 calendar days and 30 naturally completed paper trades proposed; extend if sparse. All intended entry/exit paths and incident drills covered; operational issues resolved. |

The 30-day/30-trade threshold is an engineering observation minimum, not statistical proof or a profitability guarantee. Never force trades to meet it. Meaningful strategy/risk changes reset the relevant evidence window. Overnight sleep or an offline laptop invalidates continuous-operation claims; local development can still continue.

## M4 — Persisted risk guard and deployment readiness

| ID | Task | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| B18 | Define normalized equity accounting and implement separate persisted entry permission/guard service. | B14; risk parameters before real deployment | Tests cover fees, fills, transfers, stale data, pending orders, UTC day boundary, restarts and manual rearm. Detailed contract in risk plan. |
| B19 | Integrate guard into order confirmation and verified entry-pause API; cancel pending entries without canceling protective exits. | B18 | Fixture breach and stale heartbeat block entries; restart cannot clear latch; cancellation/fill races reconcile; existing exit rules remain active. |
| B20 | Repeat paper operational drills with guard; prepare single-host deployment bundle and recovery guide. | B16, B19; hosting decision | Measured heartbeat/response bounds recorded, secrets handling reviewed, backup restored, pinned image and exact config deploy reproducibly; no paid hosting created by default. |
| B21 | Compile decision dossier and stop at live authorization boundary. | B17, B20 | Research result, risk limits, unresolved issues, venue behavior, operating responsibility, maximum capital and rollback plan presented concretely. |

B18–B20 need not block an initial paper smoke. They are required before promising daily-loss enforcement and before a live pilot is considered. A guard is a new component that must earn trust through tests; do not describe a draft watchdog as a guaranteed account-wide kill switch.

## Later work only after a separate live decision

A future user decision must specify the exact exchange/account, capital allocation, per-order stake, exposure and loss thresholds, monitoring responsibility, and stop/recovery policy. Only then create a separate live profile and credentials with no withdrawal permission, perform venue-specific verification, and consider a tightly bounded rollout. This backlog contains no authorization to fund an account, place a live order, force an exit, or enable unattended live trading.

## Minimal test portfolio

Prefer meaningful behavior tests over assertions that repeat constants. Use fixed candle sequences and fake exchange/API responses. Keep network tests opt-in and read-only until an explicitly approved live test. Test configuration merging using the actual selected version. In CI run project tests and relevant upstream tests for any touched integration point; do not claim full upstream validation if only project tests ran. Reports distinguish unit tests, historical simulations, paper observations, and real exchange behavior.
