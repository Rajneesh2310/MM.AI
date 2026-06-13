# MM.AI Observation Builder Validation Report

Run timestamp: 25:05:26 10:42:32 (DD:MM:YY HH:MM:SS, local IST)
Install root: `C:\Users\DELL\MMMarket`
Lookback sessions: 5
Builder: `src.observation_builder.build_observations`

## Symbols tested

- RELIANCE
- INFY
- NIFTY

## Unit tests

- Suite: `tests/test_observation_builder.py`
- Result: 8 / 8 passed
- Full project suite (`tests/`): 15 / 15 passed
- Linter errors: 0

## Observable fields generated per symbol

All three symbols produced these top-level fields (none missing): `symbol`, `timestamp`, `lookback_sessions`, `cash`, `fo`.

`cash` subfields generated for every symbol:
`latest_session`, `previous_session`, `latest_close`, `previous_close`, `close_delta`, `latest_volume`, `previous_volume`, `volume_delta`, `latest_delivery_qty`, `previous_delivery_qty`, `delivery_qty_delta`, `latest_delivery_percent`, `previous_delivery_percent`, `delivery_percent_delta`.

`fo` subfields generated for every symbol:
`latest_session`, `previous_session`, `latest_fo_row_count`, `previous_fo_row_count`, `latest_oi_total`, `previous_oi_total`, `oi_delta`, `latest_chg_in_oi_total`, `latest_contracts_total`, `previous_contracts_total`, `contracts_delta`.

## RELIANCE

- `cash.latest_session`: 2026-05-20
- `cash.previous_session`: 2026-05-19
- `cash.latest_close`: 1359.7
- `cash.previous_close`: 1322.7
- `cash.close_delta`: 37.0
- `cash.latest_volume`: 13248515.0
- `cash.previous_volume`: 21665501.0
- `cash.volume_delta`: -8416986.0
- `cash.latest_delivery_qty`: null
- `cash.previous_delivery_qty`: null
- `cash.delivery_qty_delta`: null
- `cash.latest_delivery_percent`: null
- `cash.previous_delivery_percent`: null
- `cash.delivery_percent_delta`: null
- `fo.latest_session`: 2026-05-20
- `fo.previous_session`: 2026-05-19
- `fo.latest_fo_row_count`: 244
- `fo.previous_fo_row_count`: 241
- `fo.latest_oi_total`: 118900500.0
- `fo.previous_oi_total`: 119281500.0
- `fo.oi_delta`: -381000.0
- `fo.latest_chg_in_oi_total`: -381000.0
- `fo.latest_contracts_total`: 831208.0
- `fo.previous_contracts_total`: 495354.0
- `fo.contracts_delta`: 335854.0
- Null fields: 6 (all delivery cash fields)
- Deltas generated: 5 non-null (close, volume, OI, contracts, chg_in_oi_total) ; 1 null (delivery)
- Validation: success

## INFY

- `cash.latest_session`: 2026-05-20
- `cash.previous_session`: 2026-05-19
- `cash.latest_close`: 1193.7
- `cash.previous_close`: 1196.9
- `cash.close_delta`: -3.2000000000000455
- `cash.latest_volume`: 15121010.0
- `cash.previous_volume`: 32175705.0
- `cash.volume_delta`: -17054695.0
- `cash.latest_delivery_qty`: null
- `cash.previous_delivery_qty`: null
- `cash.delivery_qty_delta`: null
- `cash.latest_delivery_percent`: null
- `cash.previous_delivery_percent`: null
- `cash.delivery_percent_delta`: null
- `fo.latest_session`: 2026-05-20
- `fo.previous_session`: 2026-05-19
- `fo.latest_fo_row_count`: 240
- `fo.previous_fo_row_count`: 236
- `fo.latest_oi_total`: 67244000.0
- `fo.previous_oi_total`: 68173600.0
- `fo.oi_delta`: -929600.0
- `fo.latest_chg_in_oi_total`: -929600.0
- `fo.latest_contracts_total`: 275059.0
- `fo.previous_contracts_total`: 421496.0
- `fo.contracts_delta`: -146437.0
- Null fields: 6 (all delivery cash fields)
- Deltas generated: 5 non-null (close, volume, OI, contracts, chg_in_oi_total) ; 1 null (delivery)
- Validation: success

## NIFTY

- `cash.latest_session`: null
- `cash.previous_session`: null
- `cash.latest_close`: null
- `cash.previous_close`: null
- `cash.close_delta`: null
- `cash.latest_volume`: null
- `cash.previous_volume`: null
- `cash.volume_delta`: null
- `cash.latest_delivery_qty`: null
- `cash.previous_delivery_qty`: null
- `cash.delivery_qty_delta`: null
- `cash.latest_delivery_percent`: null
- `cash.previous_delivery_percent`: null
- `cash.delivery_percent_delta`: null
- `fo.latest_session`: 2026-05-20
- `fo.previous_session`: 2026-05-19
- `fo.latest_fo_row_count`: 1872
- `fo.previous_fo_row_count`: 1950
- `fo.latest_oi_total`: 396523885.0
- `fo.previous_oi_total`: 714002280.0
- `fo.oi_delta`: -317478395.0
- `fo.latest_chg_in_oi_total`: 65799370.0
- `fo.latest_contracts_total`: 44475382.0
- `fo.previous_contracts_total`: 417021327.0
- `fo.contracts_delta`: -372545945.0
- Null fields: 14 (entire cash block — no cash parquet present for NIFTY)
- Deltas generated: 4 non-null (OI, contracts, chg_in_oi_total, plus implicit row-count differential); 0 cash deltas (all null)
- Validation: success

## Aggregate validation

- Symbols processed without exception: 3 / 3
- Cash deltas produced where data exists: RELIANCE, INFY
- F&O deltas produced for all three symbols (RELIANCE, INFY, NIFTY)
- Delivery deltas produced: 0 / 3 (delivery columns null in source parquet for all three)
- Timestamp format check: `DD:MM:YY HH:MM:SS` (matches `^\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$`)

## Warnings / errors

- RELIANCE cash delivery columns null on source parquet → all delivery observations null. No error raised.
- INFY cash delivery columns null on source parquet → all delivery observations null. No error raised.
- NIFTY cash parquet absent on source install → entire cash block null. No error raised.
- INFY `close_delta` carries an IEEE-754 representation artefact (`-3.2000000000000455`) from direct subtraction of two parquet floats; no rounding is applied (deterministic raw arithmetic).
- No exceptions raised during any of the three runs.
- No interpretation, narrative, prediction, recommendation, or hidden-intent inference was produced.
