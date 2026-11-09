# FRED (Federal Reserve Economic Data) Connector for Cognee

The `fred_source` connector ingests macroeconomic time-series data and indicators from the **St. Louis Federal Reserve (FRED)** directly into Cognee's semantic and graph memory.

Finance, research, risk management, and executive teams can maintain continuous memory of macroeconomic indicators (e.g. GDP, unemployment rates, CPI inflation, Federal Funds Rate) and query them through Cognee.

## Features

- **Broad Macro Coverage**: Select specific series IDs (`GDP`, `UNRATE`, `CPIAUCSL`, `FEDFUNDS`, `T10Y2Y`) or resolve series dynamically using keyword search.
- **Bounded History**: Automatically caps the observation history (default `max_observations=60`) to keep context windows and tokens focused on relevant trends.
- **Incremental Synchronization**: Automatically tracks the latest observation date in state and only pulls newly released data points on subsequent runs.
- **Discontinued Detection**: Emits `_deleted: True` tombstones if a series has been discontinued by the Federal Reserve.

## Prerequisites

FRED provides free API keys with instant registration and generous rate limits (120 requests/minute).
Obtain a free key at [fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html).

Export the key in your environment or pass it directly:

```bash
export FRED_API_KEY="your-fred-api-key"
```

## Quickstart

```python
import cognee
from cognee.tasks.ingestion.connectors import fred_source

await cognee.remember(
    fred_source(
        series_ids=["GDP", "UNRATE", "CPIAUCSL", "FEDFUNDS"],
        max_observations=60,
    ),
    dataset_name="macroeconomics",
    primary_key="id",
    write_disposition="merge",
    max_rows_per_table=0,
)
```

## Answering Questions with Memory

Once ingested into Cognee, your team can ask natural language questions:

```python
response = await cognee.search(
    query="How has the US unemployment rate trended over the past year and what was the latest rate?"
)
print(response)
```
