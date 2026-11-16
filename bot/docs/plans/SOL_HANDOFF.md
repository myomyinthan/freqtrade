# Handoff from GPT Astra to GPT-6.1 Sol

Prepared by GPT Astra on 2026-11-16 for implementation by `gpt-6.1-sol`. This document is ready to paste into a Sol chat **when the user chooses to begin implementation**. The current request produced plans only; no fork, implementation, installs, backtests, pilot or live authorization are implied.

---

You are GPT-6.1 Sol implementing the first milestone of a personal Freqtrade-based trading bot. Work from `/Users/myomyinthan/Documents/AiTrading/FreqTradingBot` and read `docs/plans/README.md`, `LOCAL_READINESS.md`, then the numbered plans. Inspect any current `AGENTS.md`, files, Git state and tool availability before changing anything. Preserve existing work.

Confirmed requirements: **spot only, dry-run first**. Unknown: exchange, quote currency, pairs, capital/risk budget, hosting, alert destination and verified GitHub owner. Do not infer these from timezone or examples. Start independent local work; resolve missing inputs only before their dependent steps. No live orders, funding, paid infrastructure, credentials collection for unnecessary access, or force exits are authorized.

Implement **M0 / B01–B05** from `02_EXECUTION_BACKLOG.md` and stop with a reviewable result. Recheck readiness: Git/gh exist, but GitHub connectivity prevented authentication validation; Docker CLI exists, but its configured daemon socket was absent and `docker compose` was unavailable; default Python 3.9.6 is below the inspected stable requirement. These are observations to recheck, not proof of permanently broken credentials. Do not silently install tools or replace system Python.

Verify the authenticated personal GitHub owner and existing fork before creating/reusing `freqtrade/freqtrade` under that account. Safely clone into a new `FreqTradingBot/freqtrade` child directory, never clone into the non-empty planning directory. Keep `origin` as the personal fork and `upstream` as the official repository. Choose a released stable version and verify its full commit SHA and matching runtime image digest/platform; do not guess a latest release or rely on mutable tags. If GitHub/runtime access blocks part of M0, complete independent templates/tests and report exactly which verification remains pending.

Keep custom files under `bot/` in the fork, copy plans to `bot/docs/plans/`, and leave upstream engine code unchanged. Use tracked names such as `bot/configs/base.example.json` and `bot/compose.yaml`; upstream ignores broad `config*.json`, `user_data/*` and `docker-compose-*.yml` patterns. Keep runtime DBs, market data, reports and secrets ignored. Record upstream/runtime pins in `VERSION.lock.json`; record overlay commit/dirty status in a generated run manifest after committing.

Implement a safe paper preflight/runner that checks resolved configuration including environment overrides, requires `dry_run=true` and spot mode, rejects force-entry and live DB reuse, and fails on unresolved venue/quote/stake inputs. M0 needs schema/runner checks, not a trading strategy; defer baseline loading to M1 or use an explicitly inert fixture. Verify with tests that a `dry_run=false` override cannot launch through the paper runner. Do not start a real exchange-specific paper pilot yet.

For later milestones, follow the registered 1h SMA20/50 baseline as an unproven hypothesis, chronological training/validation/untouched test and walk-forward protocol, fees/slippage stress, `--enable-protections`, lookahead and recursive checks. No trades or untested signals mean inconclusive analysis. Keep paper engineering success separate from economic success. No Kubernetes, custom UI, FreqAI or automatic optimization initially.

The risk plan specifies a later separate persisted daily entry-halt guard, not a guaranteed loss ceiling or automatic liquidation. It must handle mark-to-market equity, fees/transfers, pending-entry cancellation races, restart persistence and stale data while preserving normal exits. Verify the pinned engine's callback exception semantics: the inspected stable `confirm_trade_entry` wrapper defaults to approval on escaped exceptions, so guard errors must be caught and return `False`, with integration tests. Early paper smoke can precede this guard if plainly labeled; live consideration cannot.

End M0 with: files changed, owned-fork/remote status, verified pins, safety checks actually executed, unresolved blockers and the next small milestone. Do not claim unrun checks passed. Do not proceed automatically to live trading or paid deployment. Ask the user to choose the exchange and quote before exchange-dependent work, with any remaining material questions bundled concisely.

---

The full acceptance criteria and runbooks are authoritative within this project; the chosen release's actual interfaces must be verified before implementing their command templates.
