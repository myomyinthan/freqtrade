# Binance USDT spot capability

Checked 2026-11-16 from this machine, before the H001 historical study. Public market data only. No API key, account, or order was used.

| Item | Record |
| --- | --- |
| Venue | Binance spot, Freqtrade exchange ID `binance`. Official global API `https://api.binance.com`. |
| Pinned engine | Freqtrade 2026.10, commit `4cf0351e08d26e96a6429ef48103b726bb230cf8`. The Binance class supports spot and USD-M futures. This project resolves `trading_mode=spot` and rejects anything else. |
| Pair format | CCXT spot symbols `BTC/USDT`, `ETH/USDT`, `SOL/USDT`. |
| Quote and wallet | USDT paper wallet `1000`. Fixed stake `50`, which is 5% of that wallet. At most two open positions. |
| Market status | All three symbols returned `TRADING` and `isSpotTradingAllowed=true` from `GET /api/v3/exchangeInfo` at server time `2026-11-16T07:56:16Z`. |
| Listing evidence | Earliest public 1h candle: BTC and ETH `2017-08-17T04:00:00Z`; SOL `2020-08-11T06:00:00Z`. The study starts at `2024-01-01` so every selected pair has prior history. This is a present-day static list, so it carries survivorship bias. |
| Precision and limits | Tick size `0.01` USDT on all three. Lot step `0.00001` BTC, `0.0001` ETH, `0.001` SOL. Minimum notional `5` USDT, including market orders. The `50` USDT stake is above that minimum. |
| Order types | Spot `LIMIT`, `LIMIT_MAKER`, `MARKET`, `STOP_LOSS`, `STOP_LOSS_LIMIT`, `TAKE_PROFIT`, `TAKE_PROFIT_LIMIT`. Freqtrade can place an exchange stop-loss-limit. The paper config does not enable exchange stops. Backtests simulate the strategy stop inside candles. |
| Fees | Public regular-user spot schedule is `0.100%` maker and `0.100%` taker per side. BNB payment would reduce that to `0.075%`. No account tier was available, so the study uses `0.001` taker per side and labels it provisional. Source: [Binance spot fee schedule](https://www.binance.com/en/fee/trading), read 2026-11-16. |
| Rate limit | `REQUEST_WEIGHT` `6000` per minute on the public API. |
| History path | Pinned Freqtrade loads spot `5m` from `https://data.binance.vision` daily archives, then fills the recent tail from REST. Spot `1h` uses REST. Archives lag about two days, so the frozen end is `2026-11-14`. |
| Startup supply | The venue can provide far more than the 100-hour strategy warmup and the 400-hour recursive check. |
| Account access | Public candles downloaded successfully from this network. That does not show whether a Binance account can be opened or used from the operator's jurisdiction. |

The frozen dataset `20240101-20261114` passed the candle audit on 2026-11-16. Each requested hour and 5-minute slot is present once, OHLC bounds are valid, and no row has zero volume. Five-minute files end at `2026-11-13T23:55:00Z`. Hourly files also contain 55 candles after the frozen end, through `2026-11-16T06:00:00Z`; those rows are outside the registered range and are not part of the study. Manifest `be44e132bb5531fb41a783a5e558f15845f059239f67cef286e92beac46c49aa`.

Intended evaluation windows, chosen from the calendar before reading strategy results. The download starts 408 hours before the first training candle.

| Window | UTC range | Role |
| --- | --- | --- |
| train | `20240118-20250928` | Oldest 619 of 1031 evaluation days. |
| validation | `20250928-20260422` | Next 206 days. |
| test | `20260422-20261114` | Newest 206 days. Do not open until the candidate is frozen. |
| walk-forward-1 … 7 | 91-day slices from `20240718-20241017` through `20260115-20260416` | Forward slices inside the first 80%. Each follows 182 days of earlier data and ends before the untouched test. |
