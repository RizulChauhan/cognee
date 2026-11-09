import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import pytest

try:
    from cognee.tasks.ingestion.connectors.nuget import (
        NuGetClient,
        NuGetError,
        format_package_document,
        nuget_source,
    )
except (ImportError, ModuleNotFoundError):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../tasks/ingestion/connectors")))
    from nuget import (
        NuGetClient,
        NuGetError,
        format_package_document,
        nuget_source,
    )


class TestNuGetConnector(unittest.TestCase):
    """Hermetic unit tests for the NuGet v3 connector."""

    def test_discover_endpoints_fallback(self):
        """Verify endpoint fallback when network fails."""
        client = NuGetClient(index_url="https://invalid.test/index.json")
        endpoints = client.discover_endpoints()
        assert "RegistrationsBaseUrl" in endpoints
        assert "SearchQueryService" in endpoints
        assert endpoints["RegistrationsBaseUrl"] == "https://api.nuget.org/v3/registration5-gz-semver2/"

    def test_format_package_document_standard(self):
        """Verify normal package version document formatting."""
        entry = {
            "title": "Newtonsoft.Json",
            "version": "13.0.3",
            "authors": "James Newton-King",
            "description": "Json.NET is a popular high-performance JSON framework for .NET",
            "licenseExpression": "MIT",
            "projectUrl": "https://www.newtonsoft.com/json",
            "listed": True,
        }
        doc = format_package_document("Newtonsoft.Json", "13.0.3", entry)
        assert doc["id"] == "nuget:package:newtonsoft.json:13.0.3"
        assert doc["title"] == "Newtonsoft.Json 13.0.3"
        assert doc["_deleted"] is False
        assert "MIT" in doc["content"]
        assert "James Newton-King" in doc["content"]

    def test_format_package_document_deprecation(self):
        """Verify deprecation notices are surfaced."""
        entry = {
            "title": "WindowsAzure.Storage",
            "version": "9.3.3",
            "description": "Legacy client library for Azure Storage.",
            "listed": True,
            "deprecation": {
                "reasons": ["Legacy"],
                "alternatePackage": {"id": "Azure.Storage.Blobs"},
                "message": "Please migrate to the new Azure SDK packages.",
            },
        }
        doc = format_package_document("WindowsAzure.Storage", "9.3.3", entry)
        assert "[DEPRECATION NOTICE]" in doc["content"]
        assert "Azure.Storage.Blobs" in doc["content"]
        assert "Legacy" in doc["content"]

    def test_format_package_document_vulnerabilities(self):
        """Verify vulnerability advisories and severities are formatted."""
        entry = {
            "title": "Newtonsoft.Json",
            "version": "12.0.2",
            "description": "JSON framework",
            "listed": True,
            "vulnerabilities": [
                {
                    "advisoryUrl": "https://github.com/advisories/GHSA-5crp-9r3c-p9vr",
                    "severity": "High",
                }
            ],
        }
        doc = format_package_document("Newtonsoft.Json", "12.0.2", entry)
        assert "[SECURITY VULNERABILITIES]" in doc["content"]
        assert "GHSA-5crp-9r3c-p9vr" in doc["content"]
        assert "High" in doc["content"]

    def test_format_package_document_unlisted_tombstone(self):
        """Verify unlisted packages emit _deleted=True tombstones."""
        entry = {
            "title": "OldPackage",
            "version": "0.1.0-alpha",
            "description": "Test unlisted build",
            "listed": False,
        }
        doc = format_package_document("OldPackage", "0.1.0-alpha", entry)
        assert doc["_deleted"] is True

    def test_nuget_source_generator(self):
        """Verify that nuget_source yields valid documents from mock client."""
        mock_client = MagicMock()
        mock_client.get_package_registration.return_value = {
            "items": [
                {
                    "items": [
                        {
                            "catalogEntry": {
                                "title": "Serilog",
                                "version": "3.1.1",
                                "authors": "Serilog Contributors",
                                "description": "Simple .NET logging with fully-structured events",
                                "listed": True,
                            }
                        }
                    ]
                }
            ]
        }

        docs = list(nuget_source(package_ids=["Serilog"], client=mock_client))
        assert len(docs) == 1
        assert docs[0]["id"] == "nuget:package:serilog:3.1.1"
        assert "Serilog Contributors" in docs[0]["content"]


if __name__ == "__main__":
    unittest.main()
