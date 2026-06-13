# MM.AI Smoke Test Validation Report

Run timestamp: 2026-05-25 10:37 (IST)
Install root: `C:\Users\DELL\MMMarket`
Cash root: `C:\Users\DELL\MMMarket\data\cash`
F&O root: `C:\Users\DELL\MMMarket\data\fo`
Command form: `python -m src.smoke_test <SYMBOL> --lookback 5`

## RELIANCE

- Symbol: `RELIANCE`
- Cash parquet files detected: 1 (`YEAR=2026.parquet`)
- F&O parquet files detected: 1 (`YEAR=2026.parquet`)
- Total cash rows loaded: 5
- Total F&O rows loaded: 1192
- Latest cash session date: 2026-05-20
- Latest F&O session date: 2026-05-20
- Latest cash CLOSE: 1359.7
- Latest cash VOLUME: 13248515.0
- Latest F&O session row count: 244
- Latest F&O OPEN_INT rows count: 244
- Multi-year merge validation: single-year shard on disk (`YEAR=2026.parquet`); multi-year glob path executed without error
- Exit code: 0
- Warnings / errors: none

## INFY

- Symbol: `INFY`
- Cash parquet files detected: 1 (`YEAR=2026.parquet`)
- F&O parquet files detected: 1 (`YEAR=2026.parquet`)
- Total cash rows loaded: 5
- Total F&O rows loaded: 1172
- Latest cash session date: 2026-05-20
- Latest F&O session date: 2026-05-20
- Latest cash CLOSE: 1193.7
- Latest cash VOLUME: 15121010.0
- Latest F&O session row count: 240
- Latest F&O OPEN_INT rows count: 240
- Multi-year merge validation: single-year shard on disk (`YEAR=2026.parquet`); multi-year glob path executed without error
- Exit code: 0
- Warnings / errors: none

## NIFTY

- Symbol: `NIFTY`
- Cash parquet files detected: 0
- F&O parquet files detected: 1 (`YEAR=2026.parquet`)
- Total cash rows loaded: 0
- Total F&O rows loaded: 9672
- Latest cash session date: n/a
- Latest F&O session date: 2026-05-20
- Latest cash CLOSE: n/a
- Latest cash VOLUME: n/a
- Latest F&O session row count: 1872
- Latest F&O OPEN_INT rows count: 1872
- Multi-year merge validation: single-year shard on disk (`YEAR=2026.parquet`); multi-year glob path executed without error
- Exit code: 0
- Warnings / errors: cash dataset absent — reader returned empty `CashData` without raising

## Summary

- Symbols validated: 3 (RELIANCE, INFY, NIFTY)
- Cash parquet path resolution: verified
- F&O parquet path resolution: verified
- Multi-year merge: code path exercised on every run; no multi-year shards present in this install
- Latest-session extraction: deterministic — newest-first sort on `DATE`
- Missing-dataset handling: NIFTY cash absent, reader returned empty `CashData`, smoke test exit code 0
- Reader stability: 3/3 runs completed without exception
- Warnings / errors across all runs: 1 (NIFTY cash dataset absent)

The earlier foundation discovery report has been preserved at `report-discovery.md`.
