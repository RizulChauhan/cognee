import os
import sys
import unittest
from unittest.mock import MagicMock
import pytest

try:
    from cognee.tasks.ingestion.connectors.packagist import (
        PackagistClient,
        PackagistError,
        format_packagist_document,
        packagist_source,
    )
except (ImportError, ModuleNotFoundError):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../tasks/ingestion/connectors")))
    from packagist import (
        PackagistClient,
        PackagistError,
        format_packagist_document,
        packagist_source,
    )


class TestPackagistConnector(unittest.TestCase):
    """Hermetic unit tests for the Packagist connector."""

    def test_format_packagist_document_standard(self):
        """Verify normal package formatting."""
        data = {
            "name": "guzzlehttp/guzzle",
            "description": "Guzzle is a PHP HTTP client library",
            "repository": "https://github.com/guzzle/guzzle",
            "abandoned": False,
            "downloads": {"total": 500000000},
            "favers": 25000,
            "versions": {
                "7.8.1": {
                    "license": ["MIT"],
                    "authors": [{"name": "Michael Dowling"}],
                    "require": {
                        "php": "^7.2.5 || ^8.0",
                        "psr/http-client": "^1.0",
                    },
                }
            },
        }
        doc = format_packagist_document("guzzlehttp/guzzle", data)
        assert doc["id"] == "packagist:package:guzzlehttp/guzzle"
        assert doc["_deleted"] is False
        assert "Guzzle is a PHP HTTP client library" in doc["content"]
        assert "Michael Dowling" in doc["content"]
        assert "MIT" in doc["content"]

    def test_format_packagist_document_abandoned(self):
        """Verify abandoned package emits tombstone and replacement text."""
        data = {
            "name": "swiftmailer/swiftmailer",
            "description": "Swiftmailer, free feature-rich PHP mailer",
            "abandoned": "symfony/mailer",
            "replacement": "symfony/mailer",
            "versions": {},
        }
        doc = format_packagist_document("swiftmailer/swiftmailer", data)
        assert doc["_deleted"] is True
        assert "[ABANDONED PACKAGE]" in doc["content"]
        assert "symfony/mailer" in doc["content"]

    def test_packagist_source_generator(self):
        """Verify generator streams valid documents."""
        mock_client = MagicMock()
        mock_client.get_package.return_value = {
            "name": "monolog/monolog",
            "description": "Sends your logs to files, sockets, inboxes, databases and various web services",
            "abandoned": False,
            "downloads": {"total": 100000000},
            "favers": 20000,
            "versions": {},
        }

        docs = list(packagist_source(package_names=["monolog/monolog"], client=mock_client))
        assert len(docs) == 1
        assert docs[0]["id"] == "packagist:package:monolog/monolog"


if __name__ == "__main__":
    unittest.main()
