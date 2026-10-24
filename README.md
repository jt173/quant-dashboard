# Quant Dashboard

![CI](https://github.com/jt173/quant-dashboard/actions/workflows/ci.yml/badge.svg)

An API-first portfolio analytics and backtesting platform.

> Not financial advice. This is an educational engineering project; it does not
> execute trades or make claims about predictive performance.

## Planned scope
- Market data ingestion and storage (PostgreSQL)
- Portfolio analytics and optimization library
- Event-driven backtesting engine
- REST API (FastAPI)
- Pluggable ML models evaluated through the backtester

## Status
Early development. See the roadmap in `docs/roadmap.md`.

Requires Docker and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env
make up      # start Postgres and apply migrations
make run     # API at http://127.0.0.1:8000/docs
make test    # run the test suite
make ci      # run everything CI runs
```

## Market data

Daily prices and corporate actions are ingested from Yahoo Finance into Postgres.
Yahoo's terms limit use to personal projects

### Load data
```bash
make up         # start Postgres
make migrate    # apply migrations
make ingest     # load the tickers in data/universe.csv
```

Edit `data/universe.csv` to change the universe. Options go through `ARGS`:

```bash
make ingest ARGS="--start 2018-01-01":   # earliest date to backfill
make ingest ARGS="--resume 3"            # retry unfinished items of run 3
```

Re-running is safe, writes are upserts, and each run re-fetches the last 
7 days so late corrections are picked up.


