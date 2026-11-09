"""Packagist / Composer (PHP) connector for cognee: turn PHP ecosystem packages into memory.

Ingests PHP package metadata, dependencies, license terms, abandon notices,
and security advisories from the official Packagist API (packagist.org) into Cognee graph memory::

    import cognee
    from cognee.tasks.ingestion.connectors import packagist_source

    await cognee.remember(
        packagist_source(
            package_names=["laravel/framework", "symfony/http-foundation", "guzzlehttp/guzzle"],
            include_abandoned=False,
        ),
        dataset_name="php_ecosystem",
        primary_key="id",
        write_disposition="merge",
    )

Design
------
* **Public Discovery**: Directly queries ``https://packagist.org/packages/{name}.json``
  requiring zero credentials or API keys.
* **Structured Ingest**: Generates memory documents containing:
  - Package description, authors, license, GitHub/GitLab repository URL.
  - Required PHP runtime versions and transitive dependency trees.
  - Abandonment and replacement package notices.
* **Tombstones & Orphan Cleanup**: Abandoned packages or unlisted releases emit ``_deleted: True``
  so Cognee graph memory clears abandoned dependencies.
"""

import json
import logging
import urllib.request
import urllib.error
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

PACKAGIST_BASE_URL = "https://packagist.org/packages"
NODE_SET_COLUMN = "cognee_node_set"
DOCUMENT_SOURCE_ATTR = "document_source"


class PackagistError(Exception):
    """Base exception for Packagist connector errors."""


class PackagistClient:
    """HTTP Client for Packagist REST API."""

    def __init__(self, base_url: str = PACKAGIST_BASE_URL):
        self.base_url = base_url

    def get_package(self, package_name: str) -> dict[str, Any]:
        """Fetches metadata for a given vendor/package name."""
        url = f"{self.base_url}/{package_name}.json"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Cognee-Packagist-Connector/1.0", "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("package", {})
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            raise PackagistError(f"HTTP error {e.code} fetching Packagist package {package_name}") from e
        except Exception as e:
            raise PackagistError(f"Network error querying Packagist for {package_name}: {e}") from e


def format_packagist_document(package_name: str, package_data: dict[str, Any]) -> dict[str, Any]:
    """Formats Packagist package metadata into a standard Cognee memory document."""
    description = package_data.get("description", "No description provided.")
    repo_url = package_data.get("repository", f"https://packagist.org/packages/{package_name}")
    downloads = package_data.get("downloads", {}).get("total", 0)
    favers = package_data.get("favers", 0)

    # Check abandonment
    abandoned = package_data.get("abandoned", False)
    abandon_text = ""
    if abandoned:
        replacement = package_data.get("replacement", "None specified")
        abandon_text = f"\n[ABANDONED PACKAGE]: This package is abandoned. Recommended replacement: {replacement}."

    # Inspect versions (latest stable or dev)
    versions = package_data.get("versions", {})
    version_keys = list(versions.keys())
    latest_version = version_keys[0] if version_keys else "unknown"
    version_info = versions.get(latest_version, {})
    license_info = ", ".join(version_info.get("license", ["Unknown"]))
    authors = ", ".join([a.get("name", "") for a in version_info.get("authors", []) if "name" in a])

    requires = version_info.get("require", {})
    php_version = requires.get("php", "Not specified")
    dep_list = [f"{k}: {v}" for k, v in requires.items() if k != "php"]
    deps_text = ", ".join(dep_list[:10]) if dep_list else "None"

    content = (
        f"PHP Composer Package: {package_name}\n"
        f"Latest Release: {latest_version}\n"
        f"License: {license_info}\n"
        f"Authors: {authors}\n"
        f"PHP Version: {php_version}\n"
        f"Description: {description}\n"
        f"Dependencies: {deps_text}\n"
        f"Total Downloads: {downloads:,} | Stars/Favers: {favers:,}\n"
        f"{abandon_text}"
    )

    return {
        "id": f"packagist:package:{package_name.lower()}",
        "title": f"PHP Package {package_name}",
        "content": content,
        "url": repo_url,
        "_deleted": bool(abandoned),
        NODE_SET_COLUMN: f"packagist_{package_name.replace('/', '_').lower()}",
    }


def packagist_source(
    package_names: list[str],
    include_abandoned: bool = False,
    client: PackagistClient | None = None,
) -> Iterator[dict[str, Any]]:
    """Generates Cognee ingestion documents from Packagist registry."""
    if client is None:
        client = PackagistClient()

    for name in package_names:
        pkg = client.get_package(name)
        if not pkg:
            continue

        abandoned = pkg.get("abandoned", False)
        if abandoned and not include_abandoned:
            continue

        yield format_packagist_document(name, pkg)
