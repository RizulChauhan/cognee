import os
import sys
import unittest
from unittest.mock import MagicMock
import pytest

try:
    from cognee.tasks.ingestion.connectors.fred import (
        FredClient,
        FredAuthError,
        FredRateLimitError,
        FredError,
        format_fred_document,
        fred_source,
    )
except (ImportError, ModuleNotFoundError):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../tasks/ingestion/connectors")))
    from fred import (
        FredClient,
        FredAuthError,
        FredRateLimitError,
        FredError,
        format_fred_document,
        fred_source,
    )


class TestFredConnector(unittest.TestCase):
    """Test suite verifying FRED client, formatter, and resource behaviors."""

    def test_fred_client_init_validation(self):
        """Verify that an empty or missing API key raises ValueError."""
        with pytest.raises(ValueError, match="FRED api_key must be provided"):
            FredClient(api_key="")

    def test_fred_client_get_series_success(self):
        """Verify series metadata parsing on successful response."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "seriess": [
                {
                    "id": "GDP",
                    "title": "Gross Domestic Product",
                    "units": "Billions of Dollars",
                    "frequency": "Quarterly",
                    "seasonal_adjustment": "Seasonally Adjusted Annual Rate",
                    "last_updated": "2024-03-28",
                    "notes": "Annualized GDP data.",
                }
            ]
        }
        mock_session.get.return_value = mock_response

        client = FredClient(api_key="test_key", session=mock_session)
        series = client.get_series("GDP")

        assert series["id"] == "GDP"
        assert series["title"] == "Gross Domestic Product"
        assert series["frequency"] == "Quarterly"

    def test_fred_client_auth_error(self):
        """Verify that 401 response raises FredAuthError."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 401
        mock_session.get.return_value = mock_response

        client = FredClient(api_key="invalid_key", session=mock_session)
        with pytest.raises(FredAuthError):
            client.get_series("GDP")

    def test_fred_client_rate_limit_error(self):
        """Verify that 429 response raises FredRateLimitError."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 429
        mock_session.get.return_value = mock_response

        client = FredClient(api_key="test_key", session=mock_session)
        with pytest.raises(FredRateLimitError):
            client.get_series("GDP")

    def test_fred_client_get_observations(self):
        """Verify observations extraction with date and value ordering."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "observations": [
                {"date": "2024-01-01", "value": "28276.124"},
                {"date": "2023-10-01", "value": "27956.998"},
            ]
        }
        mock_session.get.return_value = mock_response

        client = FredClient(api_key="test_key", session=mock_session)
        observations = client.get_observations("GDP", limit=2)

        assert len(observations) == 2
        assert observations[0]["date"] == "2024-01-01"
        assert observations[0]["value"] == "28276.124"

    def test_format_fred_document(self):
        """Verify that format_fred_document constructs standard Cognee document rows."""
        meta = {
            "id": "UNRATE",
            "title": "Unemployment Rate",
            "units": "Percent",
            "frequency": "Monthly",
            "seasonal_adjustment": "Seasonally Adjusted",
            "last_updated": "2024-04-05",
            "notes": "Civilian unemployment rate.",
            "discontinued": False,
        }
        observations = [
            {"date": "2024-03-01", "value": "3.8"},
            {"date": "2024-02-01", "value": "3.9"},
        ]

        doc = format_fred_document(meta, observations)

        assert doc["id"] == "fred:series:UNRATE"
        assert doc["title"] == "Unemployment Rate (UNRATE)"
        assert "2024-03-01: 3.8 Percent" in doc["content"]
        assert doc["url"] == "https://fred.stlouisfed.org/series/UNRATE"
        assert doc["_deleted"] is False
        assert doc["cognee_node_set"] == "fred_series"

    def test_format_fred_document_discontinued(self):
        """Verify that discontinued series emit _deleted: True tombstone."""
        meta = {
            "id": "OLDSERIES",
            "title": "Discontinued Series Title",
            "units": "Index",
            "frequency": "Annual",
            "notes": "No longer tracked.",
        }
        doc = format_fred_document(meta, [])
        assert doc["_deleted"] is True

    def test_fred_source_generation(self):
        """Verify fred_source constructs and yields document records."""
        mock_client = MagicMock()
        mock_client.get_series.return_value = {
            "id": "FEDFUNDS",
            "title": "Federal Funds Effective Rate",
            "units": "Percent",
            "frequency": "Monthly",
            "seasonal_adjustment": "Not Seasonally Adjusted",
            "last_updated": "2024-04-01",
            "notes": "Federal funds rate target.",
            "discontinued": False,
        }
        mock_client.get_observations.return_value = [
            {"date": "2024-03-01", "value": "5.33"},
        ]

        items = list(
            fred_source(
                series_ids=["FEDFUNDS"],
                client=mock_client,
                max_observations=10,
            )
        )

        assert len(items) == 1
        assert items[0]["id"] == "fred:series:FEDFUNDS"
        assert "5.33 Percent" in items[0]["content"]


if __name__ == "__main__":
    unittest.main()
