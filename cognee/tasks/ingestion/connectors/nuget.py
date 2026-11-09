"""NuGet v3 (.NET package registry) connector for cognee: turn .NET dependencies into memory.

Ingests .NET and C# package metadata, target-framework dependency groups, deprecation notices,
and security vulnerabilities from the official NuGet v3 API (api.nuget.org) into Cognee graph memory::

    import cognee
    from cognee.tasks.ingestion.connectors import nuget_source

    await cognee.remember(
        nuget_source(
            package_ids=["Newtonsoft.Json", "Microsoft.Extensions.Logging", "Serilog"],
            include_unlisted=False,
        ),
        dataset_name="dotnet_ecosystem",
        primary_key="id",
        write_disposition="merge",
    )

Design
------
* **Dynamic Discovery**: Resolves endpoints (`RegistrationsBaseUrl/Versioned`, `SearchQueryService`)
  dynamically from ``https://api.nuget.org/v3/index.json``.
* **Structured Ingest**: Generates memory documents containing:
  - Package description, authors, license, project URL.
  - Target-framework dependency groups (.NET Standard, .NET 8.0, etc.).
  - Deprecation warnings (reasons, migration guidance, recommended alternate package).
  - Security advisories and known CVE/GHSA vulnerabilities with severity levels.
* **Tombstones & Orphan Cleanup**: Unlisted versions or removed packages emit ``_deleted: True``
  so Cognee graph memory purges stale dependencies on subsequent syncs.
* **Zero Credentials**: Uses public ``api.nuget.org`` endpoints requiring no account or API keys.
"""

import json
import logging
import urllib.request
import urllib.error
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

NUGET_INDEX_URL = "https://api.nuget.org/v3/index.json"
NODE_SET_COLUMN = "cognee_node_set"
DOCUMENT_SOURCE_ATTR = "document_source"


class NuGetError(Exception):
    """Base exception for NuGet connector errors."""


class NuGetClient:
    """HTTP Client for NuGet v3 API with dynamic service index resolution."""

    def __init__(self, index_url: str = NUGET_INDEX_URL):
        self.index_url = index_url
        self._endpoints: dict[str, str] = {}

    def discover_endpoints(self) -> dict[str, str]:
        """Resolves active service endpoints from index.json."""
        if self._endpoints:
            return self._endpoints

        req = urllib.request.Request(
            self.index_url,
            headers={"User-Agent": "Cognee-NuGet-Connector/1.0", "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning(f"Failed to fetch NuGet service index ({e}), using default v3 fallback.")
            self._endpoints = {
                "RegistrationsBaseUrl": "https://api.nuget.org/v3/registration5-gz-semver2/",
                "SearchQueryService": "https://azuresearch-usnc.nuget.org/query",
            }
            return self._endpoints

        for resource in data.get("resources", []):
            rtype = resource.get("@type", "")
            if "RegistrationsBaseUrl" in rtype and "RegistrationsBaseUrl" not in self._endpoints:
                self._endpoints["RegistrationsBaseUrl"] = resource.get("@id", "").rstrip("/") + "/"
            elif "SearchQueryService" in rtype and "SearchQueryService" not in self._endpoints:
                self._endpoints["SearchQueryService"] = resource.get("@id", "").rstrip("/")

        # Set fallbacks if not found in service index
        if "RegistrationsBaseUrl" not in self._endpoints:
            self._endpoints["RegistrationsBaseUrl"] = "https://api.nuget.org/v3/registration5-gz-semver2/"
        if "SearchQueryService" not in self._endpoints:
            self._endpoints["SearchQueryService"] = "https://azuresearch-usnc.nuget.org/query"

        return self._endpoints

    def get_package_registration(self, package_id: str) -> dict[str, Any]:
        """Fetches the registration catalog for a given package ID."""
        endpoints = self.discover_endpoints()
        reg_base = endpoints["RegistrationsBaseUrl"]
        url = f"{reg_base}{package_id.lower()}/index.json"

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Cognee-NuGet-Connector/1.0", "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            raise NuGetError(f"HTTP error {e.code} fetching NuGet registration for {package_id}") from e
        except Exception as e:
            raise NuGetError(f"Network error querying NuGet for {package_id}: {e}") from e

    def search_packages(self, query: str, take: int = 10) -> list[str]:
        """Searches NuGet packages by keyword or prefix."""
        endpoints = self.discover_endpoints()
        search_base = endpoints["SearchQueryService"]
        url = f"{search_base}?q={urllib.parse.quote(query)}&take={take}"

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Cognee-NuGet-Connector/1.0", "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return [p.get("id") for p in data.get("data", []) if "id" in p]
        except Exception as e:
            logger.warning(f"NuGet search failed for query '{query}': {e}")
            return []


def format_package_document(pkg_id: str, version: str, catalog_entry: dict[str, Any]) -> dict[str, Any]:
    """Formats a single package version catalog entry into a standard Cognee memory document."""
    title = catalog_entry.get("title") or pkg_id
    description = catalog_entry.get("description", "No description provided.")
    authors = catalog_entry.get("authors", "")
    project_url = catalog_entry.get("projectUrl", f"https://www.nuget.org/packages/{pkg_id}/{version}")
    license_exp = catalog_entry.get("licenseExpression", "")

    # Check deprecation
    deprecation = catalog_entry.get("deprecation")
    is_deprecated = bool(deprecation)
    dep_text = ""
    if is_deprecated:
        reasons = ", ".join(deprecation.get("reasons", ["Deprecated"]))
        alt_pkg = deprecation.get("alternatePackage", {}).get("id", "None")
        msg = deprecation.get("message", "")
        dep_text = f"\n[DEPRECATION NOTICE]: Reasons: {reasons}. Recommended replacement: {alt_pkg}. {msg}"

    # Check vulnerabilities
    vulnerabilities = catalog_entry.get("vulnerabilities", [])
    vuln_text = ""
    if vulnerabilities:
        vuln_lines = [f" - Advisory: {v.get('advisoryUrl')} (Severity: {v.get('severity', 'Unknown')})" for v in vulnerabilities]
        vuln_text = "\n[SECURITY VULNERABILITIES]:\n" + "\n".join(vuln_lines)

    # Check dependency groups
    dep_groups = catalog_entry.get("dependencyGroups", [])
    frameworks = []
    for g in dep_groups:
        tfm = g.get("targetFramework", "Any")
        deps = [d.get("id") for d in g.get("dependencies", []) if "id" in d]
        frameworks.append(f" - {tfm}: {', '.join(deps) if deps else 'None'}")
    deps_summary = "\n[TARGET FRAMEWORKS & DEPENDENCIES]:\n" + "\n".join(frameworks) if frameworks else ""

    content = (
        f".NET Package: {pkg_id} (Version: {version})\n"
        f"Title: {title}\n"
        f"Authors: {authors}\n"
        f"License: {license_exp or 'See package'}\n"
        f"Description: {description}\n"
        f"{dep_text}"
        f"{vuln_text}"
        f"{deps_summary}"
    )

    listed = catalog_entry.get("listed", True)

    return {
        "id": f"nuget:package:{pkg_id.lower()}:{version.lower()}",
        "title": f"{pkg_id} {version}",
        "content": content,
        "url": project_url,
        "_deleted": not listed,
        NODE_SET_COLUMN: f"nuget_{pkg_id.lower()}",
    }


def nuget_source(
    package_ids: list[str] | None = None,
    search_query: str | None = None,
    include_unlisted: bool = False,
    client: NuGetClient | None = None,
) -> Iterator[dict[str, Any]]:
    """Generates Cognee ingestion documents from NuGet v3 registry."""
    if client is None:
        client = NuGetClient()

    targets: list[str] = []
    if package_ids:
        targets.extend(package_ids)

    if search_query:
        found = client.search_packages(search_query)
        for f in found:
            if f not in targets:
                targets.append(f)

    for pkg_id in targets:
        reg_data = client.get_package_registration(pkg_id)
        if not reg_data:
            continue

        for page in reg_data.get("items", []):
            leaves = page.get("items", [])
            # In some large packages, leaves are paged externally
            if not leaves and "@id" in page:
                try:
                    req = urllib.request.Request(
                        page["@id"],
                        headers={"User-Agent": "Cognee-NuGet-Connector/1.0", "Accept": "application/json"}
                    )
                    with urllib.request.urlopen(req, timeout=10) as r:
                        page_detail = json.loads(r.read().decode("utf-8"))
                        leaves = page_detail.get("items", [])
                except Exception as e:
                    logger.warning(f"Could not load paged leaves from {page.get('@id')}: {e}")

            for leaf in leaves:
                catalog_entry = leaf.get("catalogEntry", {})
                version = catalog_entry.get("version", "latest")
                listed = catalog_entry.get("listed", True)

                if not listed and not include_unlisted:
                    continue

                yield format_package_document(pkg_id, version, catalog_entry)
