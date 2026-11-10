import os
import sys
import unittest
from unittest.mock import MagicMock
import pytest

try:
    from cognee.tasks.ingestion.connectors.hexpm import (
        HexpmClient,
        HexpmError,
        format_hexpm_document,
        hexpm_source,
    )
except (ImportError, ModuleNotFoundError):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../tasks/ingestion/connectors")))
    from hexpm import (
        HexpmClient,
        HexpmError,
        format_hexpm_document,
        hexpm_source,
    )


class TestHexpmConnector(unittest.TestCase):
    """Hermetic unit tests for the Hex.pm connector."""

    def test_format_hexpm_document_standard(self):
        """Verify normal package formatting."""
        data = {
            "name": "phoenix",
            "html_url": "https://hex.pm/packages/phoenix",
            "meta": {
                "description": "Peace of mind from prototype to production",
                "licenses": ["MIT"],
                "links": {"GitHub": "https://github.com/phoenixframework/phoenix"},
            },
            "releases": [{"version": "1.7.14"}],
            "retirement": None,
            "downloads": {"all": 85000000},
        }
        doc = format_hexpm_document("phoenix", data)
        assert doc["id"] == "hexpm:package:phoenix"
        assert doc["_deleted"] is False
        assert "Peace of mind" in doc["content"]
        assert "1.7.14" in doc["content"]
        assert "MIT" in doc["content"]

    def test_format_hexpm_document_retired(self):
        """Verify retired package emits tombstone and retirement text."""
        data = {
            "name": "poison",
            "meta": {
                "description": "An experimental Elixir JSON library",
                "licenses": ["CC0-1.0"],
                "links": {},
            },
            "releases": [{"version": "5.0.0"}],
            "retirement": {
                "reason": "deprecated",
                "message": "Use Jason instead for better performance.",
            },
            "downloads": {"all": 100000000},
        }
        doc = format_hexpm_document("poison", data)
        assert doc["_deleted"] is True
        assert "[RETIRED PACKAGE]" in doc["content"]
        assert "Use Jason instead" in doc["content"]

    def test_hexpm_source_generator(self):
        """Verify generator streams valid documents."""
        mock_client = MagicMock()
        mock_client.get_package.return_value = {
            "name": "ecto",
            "meta": {
                "description": "A toolkit for data mapping and language integrated query for Elixir",
                "licenses": ["Apache-2.0"],
                "links": {},
            },
            "releases": [{"version": "3.11.2"}],
            "retirement": None,
            "downloads": {"all": 60000000},
        }

        docs = list(hexpm_source(package_names=["ecto"], client=mock_client))
        assert len(docs) == 1
        assert docs[0]["id"] == "hexpm:package:ecto"


if __name__ == "__main__":
    unittest.main()
