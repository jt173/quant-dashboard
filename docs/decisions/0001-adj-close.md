## Context
Phase 1 needs free historical daily prices with correct handling of splits and dividends. The data source may change later, 
so the rest of the system must not depend on one provider's quirks.

- The first data source is yfinance, the adapter (ingestion/yahoo.py) returns provider-neutral dataclasses, nothing else imports yfinance
- Store yfinance adj_close only as a cross-check, compute adjustments ourselves.
- Implementing plain dataclasses in the data access layer.
- The analytics library will convert to pandas dataframe.
- Yahoo close data is already split-adjusted, so the data access layer should adjust for dividends only