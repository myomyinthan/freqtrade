"""Validate downloaded hourly and five-minute spot candles before freezing a dataset."""

import hashlib

import numpy as np
import pandas as pd


def audit_file(path, start, end, minutes):
    data = pd.read_feather(path)
    columns = ["date", "open", "high", "low", "close", "volume"]
    if any(column not in data for column in columns):
        raise ValueError(f"{path.name}: missing OHLCV columns")
    dates = pd.to_datetime(data["date"], utc=True, errors="raise")
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError(f"{path.name}: timestamps are missing, duplicated or out of order")
    period = pd.Timedelta(minutes=minutes)
    if (dates != dates.dt.floor(period)).any():
        raise ValueError(f"{path.name}: candles fall outside UTC timeframe boundaries")
    if (dates + period > pd.Timestamp.now(tz="UTC")).any():
        raise ValueError(f"{path.name}: contains an unfinished candle")
    values = data[columns[1:]]
    if not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError(f"{path.name}: nonfinite OHLCV")
    if (
        (values[["open", "high", "low", "close"]] <= 0).any().any()
        or (values["volume"] < 0).any()
        or (values["high"] < values[["open", "low", "close"]].max(axis=1)).any()
        or (values["low"] > values[["open", "high", "close"]].min(axis=1)).any()
    ):
        raise ValueError(f"{path.name}: invalid OHLCV bounds")
    expected = pd.date_range(start, end, freq=period, inclusive="left")
    actual = pd.DatetimeIndex(dates[(dates >= start) & (dates < end)])
    missing = expected.difference(actual)
    if len(missing):
        raise ValueError(f"{path.name}: {len(missing)} missing candles, first at {missing[0]}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "name": path.name, "sha256": digest, "rows": len(data), "requested_rows": len(expected),
        "first_utc": dates.iloc[0].isoformat(), "last_utc": dates.iloc[-1].isoformat(),
        "zero_volume_rows": int(values["volume"].eq(0).sum()),
    }


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start")
    parser.add_argument("end")
    parser.add_argument("--minutes", required=True, type=int, choices=(5, 60))
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        start, end = (pd.to_datetime(s, format="%Y%m%d", utc=True) for s in (args.start, args.end))
        print(json.dumps([audit_file(path, start, end, args.minutes) for path in args.files]))
    except (OSError, TypeError, ValueError) as exc:
        parser.exit(2, f"Dataset audit failed: {exc}\n")
