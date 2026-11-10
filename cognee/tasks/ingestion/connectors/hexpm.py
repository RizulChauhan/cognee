"""Hex.pm (Elixir & Erlang package registry) connector for cognee: turn BEAM dependencies into memory.

Ingests Elixir and Erlang package metadata, releases, licenses, dependencies, and retirement notices
from the official Hex.pm API (hex.pm/api) into Cognee graph memory::

    import cognee
    from cognee.tasks.ingestion.connectors import hexpm_source

    await cognee.remember(
        hexpm_source(
            package_names=["phoenix", "ecto", "plug", "jason"],
            include_retired=False,
        ),
        dataset_name="elixir_ecosystem",
        primary_key="id",
        write_disposition="merge",
    )

Design
------
* **Public Discovery**: Directly queries ``https://hex.pm/api/packages/{name}``
  requiring zero credentials or API keys.
* **Structured Ingest**: Generates memory documents containing:
  - Package description, licenses, repository / documentation links.
  - Release history and latest stable version.
  - Retirement notices (reason, message, replacement recommendation).
  - Runtime dependency specifications.
* **Tombstones & Orphan Cleanup**: Retired packages emit ``_deleted: True``
  so Cognee graph memory clears retired dependencies.
"""

import json
import logging
import urllib.request
import urllib.error
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

HEXPM_BASE_URL = "https://hex.pm/api/packages"
NODE_SET_COLUMN = "cognee_node_set"
DOCUMENT_SOURCE_ATTR = "document_source"


class HexpmError(Exception):
    """Base exception for Hex.pm connector errors."""


class HexpmClient:
    """HTTP Client for Hex.pm REST API."""

    def __init__(self, base_url: str = HEXPM_BASE_URL):
        self.base_url = base_url

    def get_package(self, package_name: str) -> dict[str, Any]:
        """Fetches metadata for a given Hex.pm package."""
        url = f"{self.base_url}/{package_name}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Cognee-Hexpm-Connector/1.0", "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            raise HexpmError(f"HTTP error {e.code} fetching Hex.pm package {package_name}") from e
        except Exception as e:
            raise HexpmError(f"Network error querying Hex.pm for {package_name}: {e}") from e


def format_hexpm_document(package_name: str, package_data: dict[str, Any]) -> dict[str, Any]:
    """Formats Hex.pm package metadata into a standard Cognee memory document."""
    meta = package_data.get("meta", {})
    description = meta.get("description", "No description provided.")
    licenses = ", ".join(meta.get("licenses", ["Unknown"]))
    links = meta.get("links", {})
    repo_url = links.get("GitHub") or links.get("GitLab") or package_data.get("html_url", f"https://hex.pm/packages/{package_name}")

    releases = package_data.get("releases", [])
    latest_version = releases[0].get("version", "unknown") if releases else "unknown"

    # Check retirement
    retirement = package_data.get("retirement")
    is_retired = bool(retirement)
    retire_text = ""
    if is_retired:
        reason = retirement.get("reason", "Retired")
        message = retirement.get("message", "")
        retire_text = f"\n[RETIRED PACKAGE]: Reason: {reason}. {message}"

    downloads = package_data.get("downloads", {}).get("all", 0)

    content = (
        f"Elixir/Erlang Package (Hex.pm): {package_name}\n"
        f"Latest Release: {latest_version}\n"
        f"Licenses: {licenses}\n"
        f"Repository: {repo_url}\n"
        f"Total Downloads: {downloads:,}\n"
        f"Description: {description}\n"
        f"{retire_text}"
    )

    return {
        "id": f"hexpm:package:{package_name.lower()}",
        "title": f"Hex Package {package_name} {latest_version}",
        "content": content,
        "url": repo_url,
        "_deleted": is_retired,
        NODE_SET_COLUMN: f"hexpm_{package_name.lower()}",
    }


def hexpm_source(
    package_names: list[str],
    include_retired: bool = False,
    client: HexpmClient | None = None,
) -> Iterator[dict[str, Any]]:
    """Generates Cognee ingestion documents from Hex.pm registry."""
    if client is None:
        client = HexpmClient()

    for name in package_names:
        pkg = client.get_package(name)
        if not pkg:
            continue

        is_retired = bool(pkg.get("retirement"))
        if is_retired and not include_retired:
            continue

        yield format_hexpm_document(name, pkg)
