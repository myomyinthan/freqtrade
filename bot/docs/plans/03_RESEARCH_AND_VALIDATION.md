# Research protocol and strategy hypothesis

## Hypothesis H001 — simple spot trend persistence

Hypothesis: on a small, liquid, preselected spot universe, a closed-candle 1h SMA20/SMA50 crossover may capture sustained moves after costs. This is a transparent test fixture and research starting point; there is no supporting result yet and no expectation of assured profit.

Implement one strategy, `PersonalSpotBaseline`, with the following fixed specification:

| Item | Initial paper/research rule |
| --- | --- |
| Mode | Long-only spot, 1h, process new closed candles only. |
| Indicators | SMA20 and SMA50 of close; calculate in indicator population; never use future rows. |
| Entry | Current SMA20 > SMA50 and previous SMA20 <= previous SMA50, positive volume, finite indicators. |
| Signal exit | Current SMA20 < SMA50 and previous SMA20 >= previous SMA50, positive volume, finite indicators. |
| Other exits | Illustrative fixed strategy stoploss `-0.05`; no trailing stop. Disable ROI exits using the pinned version's supported empty-ROI configuration, then test that signal exits and stoploss still work. |
| Warmup | Begin with 100 startup candles; prove sufficient and obtainable on selected venue. No signals during insufficient warmup. |
| Exposure fixture | At most two open positions, fixed stake of 5% of initial paper wallet per order; no compounding, DCA, pyramiding or shorting. |
| Protections fixture | One-candle per-pair cooldown; global StoplossGuard after two losing stoploss exits in 24 candles, locking entries for 6 candles. Verify supported schema. |
| Selection | Static whitelist chosen before performance inspection; no ranking by historical returns. |

The 5% stake and 5% stop are **paper fixtures**, not approved live risk. Their simple product is only a nominal loss estimate; fees, gaps, slippage, and execution failure can exceed it. Actual wallet/stake currency and pairs stay unresolved until the user supplies them. Use a wallet size large enough to meet venue minimums without changing exposure silently.

Behavior fixtures should include upward/downward/equal crossings, a trend without repeated crossings, zero volume, NaNs, insufficient startup, same-candle signal conflicts, and no short signals. For prefix invariance, calculate indicators/signals on full data and multiple historical prefixes; all overlapping closed-candle outputs must agree. Test the desired stop and exit precedence through the engine, not only Pandas functions.

## Dataset and split registration

Before inspecting results, commit `protocol.yaml` with dataset scope, pair inclusion rule, concrete UTC boundaries, strategy hash, fees, benchmark, maximum allowed variants and success/failure criteria. Proposed data target is at least 24 months spanning rising, falling and sideways conditions when the selected venue provides it. Shorter or concentrated histories reduce confidence and must be labeled.

Use approximately the oldest 60% for training, the next 20% for validation, and the newest 20% as an untouched test. Convert percentages to exact date boundaries once data availability is known. Do not randomly split candles. For the initial fixed strategy, “training” is pipeline development and plausibility review; no parameter search is required.

Use expanding or rolling walk-forward windows within the first 80%, for example 6 months of development followed by 3 months of forward validation, then advance by 3 months. Select concrete windows before runs, adjust only for documented data availability, and preserve all windows including bad ones. Freeze the final candidate and rules before opening the last 20%. If the test is used to redesign the strategy, label it consumed; future independent data is needed for a new final test.

Supply pre-window candles for warmup without counting pre-window profit. Specify fresh-start portfolio state per split; report any alternative continuous-position experiment separately. Document boundary exits and forced closes so a favorable cutoff cannot hide loss. Exclude unfinished current candles. Preserve opening positions/ending unrealized values when comparing continuous equity paths.

Data manifest: venue ID, quote currency, pair names and listing availability, timeframe, requested/actual start/end, timestamp convention, download time, format, file hashes, row counts, gaps/duplicates/outliers, and coverage exclusions. Audit monotonic UTC timestamps, expected intervals, OHLC consistency, nonnegative volume, and incomplete candles. Do not repair missing candles by inventing traded prices. Keep raw and cleaned data separate with a transformation log.

Use the selected exchange's history; do not silently replace it with another venue's candles. A present-day static liquid pairlist still has survivorship bias. Record what was knowable at the selection date and delisted/unsupported omissions; prefer historical availability evidence. Full point-in-time universes are future work if unavailable, and limited coverage must constrain conclusions. Download explicitly requested timeframes and dates rather than relying on command defaults. [Freqtrade data downloading](https://www.freqtrade.io/en/stable/data-download/).

## Validation sequence

1. Run training and validation with a fresh cache and protections explicitly enabled. Confirm intended strategy, wallet, fee, pair and stop settings from the effective config and output.
2. Run lookahead analysis over windows with enough genuine entries and exits. Review every branch and signal label. “No bias detected” only concerns tested signals; no trades, tool cancellation, or unexercised signals are **inconclusive**, never a pass. Analysis can override normal execution settings, so do not treat it as a profitability backtest. [Freqtrade lookahead analysis](https://www.freqtrade.io/en/stable/lookahead-analysis/).
3. Run recursive analysis across startup sizes such as 50, 100, 200 and 400, with a long reference series; include more than one period/regime in separate runs. It compares indicator initialization, not end-to-end trading performance. For these finite-window SMAs, expect stable values once enough history exists; additionally prove signals agree at boundary cases. Choose startup history that the live venue can supply. [Freqtrade recursive analysis](https://www.freqtrade.io/en/stable/recursive-analysis/).
4. Conduct walk-forward and stress evaluation. Freeze the candidate, hashes and decision criteria, then run the untouched test once. Archive failures and unresolved warnings.

Built-in cooldown/stoploss protections are evaluated in backtesting only when enabled with `--enable-protections`; include that flag in the research wrapper. A reported historical result must say whether protection logic was enabled. [Freqtrade protections](https://www.freqtrade.io/en/stable/plugins/#protections).

## Costs, execution realism, and benchmarks

Freqtrade's candle backtest makes execution assumptions including requested-price fills without slippage; a smaller detail timeframe can improve intrabar simulation, but cannot establish queue priority or actual execution. Historical exchange limits may also be imperfectly represented. Treat fills as simulated and compare them with paper observations. [Freqtrade backtesting assumptions](https://www.freqtrade.io/en/stable/backtesting/#assumptions-made-by-backtesting).

Use verified account-tier maker/taker fees; conservatively assume taker costs until the order policy and evidence justify otherwise. Record whether the supplied fee applies per side and ensure entry and exit costs are counted exactly once. Run a baseline fee scenario, 1.5× fee scenario, and 2× fee scenario. If actual fees are unresolved, run labeled provisional scenarios rather than guessing a true fee tier.

No undocumented slippage flag should be invented. Implement transparent post-processing of exported fills with adverse price movement of 5, 10, 25 and 50 basis points **per side**, in addition to explicit fees. Recalculate stake-weighted net outcomes and cumulative equity; state that post-processing does not re-simulate stop triggers, order feasibility, slot allocation, or altered holding periods. A raised fee may be an additional cost proxy, but must not be called an execution simulation. If stress sensitivity is material, require a better execution model and observed spreads before progression.

Where data exists, compare 1h results with a 5m detail-timeframe run. Add delayed-entry and missed-fill scenarios only with a clearly specified reproducible model; label unmodeled spread, depth, partial fills and outages as limitations. Model open orders tying up capital. Report exposure and turnover so nominal profit cannot disguise heavy capacity usage.

Benchmarks: cash held in the chosen quote currency, plus a predeclared equal-weight buy-and-hold portfolio on the same pair universe and dates with the same initial cash and costs. Also report an exposure-matched comparison or explain why full-exposure buy-and-hold is not risk-equivalent. Do not count benchmark success as strategy validation.

## Evidence and decision rules

Every report must include net return, absolute P&L, equity curve, maximum drawdown, trade count, duration, exposure, turnover, fees, win rate, average win/loss, expectancy, profit factor when defined, monthly/quarterly breakdowns, per-pair contributions, stop/other exit counts, and forced/remaining positions. State annualization conventions. Display undefined ratios as undefined, not infinity presented as strength. Use block-based uncertainty estimates when justified; few clustered trades do not support precise claims.

Pre-register gates before validation. Proposed research screening requirements are positive aggregate out-of-sample expectancy after baseline costs, non-catastrophic performance in stressed costs, no dependence on a single pair or lucky month, and drawdown within the user's eventual agreed budget. These are a screening design, not guarantees. Numeric drawdown and stress thresholds remain **TBD** until risk preferences and data are known; do not claim the economic gate passed while they are undefined.

The technical gate requires deterministic reproduction, no detected lookahead bias in exercised signals, stable startup behavior, documented data integrity and complete accounting. Economic failure means retain the pipeline and reject/revise the hypothesis. Sparse trades or insufficient regime coverage means extend observation and mark inconclusive. Do not lower gates or add indicators to rescue a disappointing untouched test.

Log every attempted variant, including abandoned ones. If the first hypothesis fails, propose at most a small predeclared set of economically motivated alternatives with fresh validation discipline. Hyperopt and FreqAI are deferred; searching many variants without accounting for selection bias can make randomness look like an edge.
