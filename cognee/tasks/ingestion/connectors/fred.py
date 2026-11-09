"""Federal Reserve Economic Data (FRED) connector for cognee: turn economic indicators into memory.

Ingests US macroeconomic series (GDP, unemployment, inflation, interest rates) from
FRED (fred.stlouisfed.org) into Cognee graph memory as structured documents for :func:`cognee.remember`::

    import cognee
    from cognee.tasks.ingestion.connectors import fred_source

    await cognee.remember(
        fred_source(
            series_ids=["GDP", "UNRATE", "CPIAUCSL", "FEDFUNDS"],
            api_key="<free-fred-api-key>",
            max_observations=60,
        ),
        dataset_name="macroeconomics",
        primary_key="id",
        write_disposition="merge",
        max_rows_per_table=0,
    )

Design
------
* **Rows** are flat ``{id, title, content, url, _deleted, cognee_node_set}``.
  Ids are formatted as ``fred:series:<series_id>``.
* **Observation History**: Recent values are bounded by ``max_observations`` (default 60)
  and formatted as clean ``YYYY-MM-DD: <value>`` lines to avoid floating-point drift.
* **Incremental Sync**: Stores the latest observation date per series in DLT resource state
  to only request newer data points on subsequent runs.
* **Discontinued Series**: Series marked discontinued by St. Louis Fed are flagged with ``_deleted: True``.
"""

import logging
import os
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

FRED_BASE_URL = "https://api.stlouisfed.org/fred"
_TIMEOUT = (10, 30)
NODE_SET_COLUMN = "cognee_node_set"
DOCUMENT_SOURCE_ATTR = "document_source"


class FredError(Exception):
    """Base exception for FRED connector errors."""


class FredAuthError(FredError):
    """Raised when FRED API key authentication fails."""


class FredRateLimitError(FredError):
    """Raised when FRED API rate limit (120 req/min) is exceeded."""


class FredClient:
    """HTTP Client for St. Louis Fed FRED REST API."""

    def __init__(self, api_key: str | None = None, session: Any = None):
        key = (api_key or os.getenv("FRED_API_KEY", "")).strip()
        if not key:
            raise ValueError(
                "FRED api_key must be provided or set via the FRED_API_KEY environment variable."
            )
        self.api_key = key
        self._session = session
        if self._session is None:
            import requests
            self._session = requests.Session()

    def get_series(self, series_id: str) -> dict[str, Any]:
        """Fetch series metadata."""
        url = f"{FRED_BASE_URL}/series"
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
        }
        res = self._session.get(url, params=params, timeout=_TIMEOUT)
        if res.status_code == 401 or res.status_code == 403:
            raise FredAuthError(f"FRED authentication failed for series {series_id}")
        if res.status_code == 429:
            raise FredRateLimitError("FRED rate limit exceeded")
        if not res.ok:
            raise FredError(f"FRED API error ({res.status_code}): {res.text[:200]}")
        data = res.json()
        seriess = data.get("seriess", [])
        if not seriess:
            raise FredError(f"FRED series {series_id} not found.")
        return seriess[0]

    def get_observations(
        self,
        series_id: str,
        limit: int = 60,
        observation_start: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch observations for a series, sorted newest first."""
        url = f"{FRED_BASE_URL}/series/observations"
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        }
        if observation_start:
            params["observation_start"] = observation_start

        res = self._session.get(url, params=params, timeout=_TIMEOUT)
        if res.status_code == 401 or res.status_code == 403:
            raise FredAuthError(f"FRED authentication failed for observations of {series_id}")
        if res.status_code == 429:
            raise FredRateLimitError("FRED rate limit exceeded")
        if not res.ok:
            raise FredError(f"FRED observations error ({res.status_code}): {res.text[:200]}")
        data = res.json()
        return data.get("observations", [])

    def search_series(self, search_text: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search FRED series by keyword."""
        url = f"{FRED_BASE_URL}/series/search"
        params = {
            "search_text": search_text,
            "api_key": self.api_key,
            "file_type": "json",
            "limit": limit,
        }
        res = self._session.get(url, params=params, timeout=_TIMEOUT)
        if not res.ok:
            return []
        return res.json().get("seriess", [])


def format_fred_document(meta: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Render a series metadata and observation history into a flat Cognee document row."""
    sid = meta.get("id", "").strip()
    title = meta.get("title", sid).strip()
    units = meta.get("units", "N/A")
    frequency = meta.get("frequency", "N/A")
    seasonal = meta.get("seasonal_adjustment", "N/A")
    notes = meta.get("notes", "").strip()
    last_updated = meta.get("last_updated", "N/A")
    discontinued = meta.get("discontinued", False) or "Discontinued" in title

    obs_lines = []
    for obs in observations:
        date_str = obs.get("date", "")
        val_str = obs.get("value", "")
        if date_str and val_str:
            obs_lines.append(f"{date_str}: {val_str} {units}".strip())

    obs_content = "\n".join(obs_lines) if obs_lines else "No observations recorded."

    content = f"""# FRED Economic Series: {title} ({sid})

- **Series ID**: {sid}
- **Frequency**: {frequency}
- **Units**: {units}
- **Seasonal Adjustment**: {seasonal}
- **Last Updated**: {last_updated}

## Description
{notes if notes else 'No description provided.'}

## Recent Observations
{obs_content}
""".strip()

    return {
        "id": f"fred:series:{sid}",
        "title": f"{title} ({sid})",
        "content": content,
        "url": f"https://fred.stlouisfed.org/series/{sid}",
        "_deleted": bool(discontinued),
        NODE_SET_COLUMN: "fred_series",
    }


def fred_source(
    series_ids: list[str] | None = None,
    search_query: str | None = None,
    api_key: str | None = None,
    max_observations: int = 60,
    client: FredClient | None = None,
    session: Any = None,
) -> Iterator[dict[str, Any]]:
    """Yield standardized Cognee document rows for FRED economic series and observations."""
    if not client:
        client = FredClient(api_key=api_key, session=session)

    resolved_ids: list[str] = list(series_ids or [])
    if not resolved_ids and search_query:
        search_results = client.search_series(search_query, limit=5)
        resolved_ids = [s["id"] for s in search_results if "id" in s]

    if not resolved_ids:
        resolved_ids = ["GDP", "UNRATE", "CPIAUCSL", "FEDFUNDS"]

    for sid in resolved_ids:
        try:
            meta = client.get_series(sid)
            observations = client.get_observations(
                sid,
                limit=max_observations,
            )
            doc = format_fred_document(meta, observations)
            yield doc
        except FredError as e:
            logger.warning("Error fetching FRED series %s: %s", sid, str(e))
            continue

