# FreqTradingBot implementation planning pack

Prepared by **GPT Astra** for **GPT-6.1 Sol (`gpt-6.1-sol`)** on 2026-11-16. This pack specifies future work; it does not claim that a fork, bot, strategy test, or deployment already exists.

The objective is a personal fork of [Freqtrade](https://github.com/freqtrade/freqtrade) with an understandable spot strategy, reproducible evaluation, and a monitored dry-run pilot. The first deliverable is a dependable research and paper-trading system. Profitability is an untested hypothesis.

## Read in this order

| File | Purpose |
| --- | --- |
| [LOCAL_READINESS.md](LOCAL_READINESS.md) | Coordinator's machine and GitHub readiness findings; recheck before bootstrap. |
| [01_ARCHITECTURE_AND_FORK.md](01_ARCHITECTURE_AND_FORK.md) | Repository bootstrap, runtime layout, version pinning, and upstream maintenance. |
| [02_EXECUTION_BACKLOG.md](02_EXECUTION_BACKLOG.md) | Small implementation tasks, dependencies, acceptance evidence, and stage gates. |
| [03_RESEARCH_AND_VALIDATION.md](03_RESEARCH_AND_VALIDATION.md) | Baseline hypothesis, data, chronological splits, bias checks, and research decisions. |
| [04_SECURITY_AND_RISK.md](04_SECURITY_AND_RISK.md) | Secrets, exposure, exchange constraints, and persisted entry-halt design. |
| [05_OPERATIONS_RUNBOOK.md](05_OPERATIONS_RUNBOOK.md) | Command templates, pilot operation, incidents, recovery, and releases. |
| [SOL_HANDOFF.md](SOL_HANDOFF.md) | Compact instructions to give Sol when implementation is authorized. |

## Decisions and open inputs

| Decision | Status | Implementation consequence |
| --- | --- | --- |
| Spot only; dry-run first | **User confirmed** | Long-only; no futures, leverage, margin, shorting, or live order placement. |
| Planning now, implementation later | **Current scope** | No fork creation, installs, paid infrastructure, exchange credentials, or trading from this pack. |
| Own GitHub fork of upstream | Intended | Verify account, existing fork, and repository ownership before creation; maintain `origin` and `upstream` separately. |
| Exchange and account jurisdiction | **Unresolved** | Do not choose a venue on the user's behalf; resolve before exchange-specific data collection or pilot configuration. |
| Quote currency and initial pairs | **Unresolved** | Do not silently assume USDT, USD, NZD, BTC, or exchange eligibility from the user's timezone. |
| Capital and accepted risk | **Unresolved** | All numbers below are paper-test fixtures; no approved live budget exists. |
| Hosting and monthly budget | **Unresolved** | Start with a local dry-run when prerequisites allow; no paid server provisioning. |
| Baseline and tooling | Proposed engineering defaults | One 1h SMA crossover strategy, static small pairlist, pinned Docker runtime, standard FreqUI optional. |
| Alerts and operator availability | **Unresolved** | Local logs first; obtain destination before enabling external notifications. |

Sol can prepare code, tests, safe config templates, and manifests without the unresolved inputs. Exchange-specific downloading and an actual pilot require exchange, quote, pairs, and a realistic paper-wallet size. Live use additionally requires explicit authorization for venue, budget, exposure limits, loss thresholds, operator response, and hosting.

## Definition of done for the initial implementation

1. An owned fork is correctly linked to upstream, with the project overlay tracked under `bot/` and an immutable runtime reference recorded.
2. Strategy, configuration, and guard tests pass; secrets and generated runtime data stay out of Git.
3. Historical evaluation is reproducible and honestly labels failed or inconclusive research. Bias checks cover executed signals, and untouched-test results are preserved.
4. A dry-run pilot passes operational acceptance with evidence of startup, trade lifecycle, restart, pause, guard failure, and recovery behavior.
5. Sol provides a reviewable result and the remaining live decision. Neither a positive backtest nor elapsed pilot time authorizes live trading.

The historical strategy may fail while the engineering deliverable succeeds. In that case keep the bot in research/dry-run, publish the failure evidence, and propose a new registered hypothesis rather than relaxing the acceptance criteria.

## Scope boundaries

One bot, one exchange, one quote currency, one database, and a small fixed pair universe. No Kubernetes, custom dashboard, paid market data, portfolio optimizer, automated parameter search, DCA, pyramiding, or FreqAI in the first iteration. Reconsider FreqAI only after a reproducible non-ML baseline exposes a specific limitation and there is sufficient independent data to evaluate the added complexity.

The linked stable documentation is a moving reference, reviewed on the preparation date. At implementation time verify every CLI flag, schema, callback, API method, and exchange behavior against the pinned release. Repository code and that release's documentation take precedence over a newer web page. This pack's threshold values and architecture choices are project proposals, not claims that upstream supplies them natively.
