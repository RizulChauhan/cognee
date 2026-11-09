# Packagist / Composer (PHP) Data Source Connector

The Packagist connector ingests PHP Composer package metadata, dependency requirements, authors, licenses, abandonment warnings, and registry statistics from the official Packagist API (`packagist.org`) into Cognee graph memory.

---

## Capabilities
- **Direct API Access**: Queries `https://packagist.org/packages/{vendor}/{package}.json` requiring zero API keys or credentials.
- **PHP Version & Dependency Tracking**: Documents minimum PHP version constraints and direct dependency packages.
- **Abandonment Alerts**: Automatically tags deprecated or abandoned packages with replacement suggestions.
- **Tombstones (`_deleted`)**: Flags abandoned packages with `_deleted: True` to trigger orphan cleanup in Cognee.

---

## Python Usage

```python
import cognee
from cognee.tasks.ingestion.connectors import packagist_source

# Ingest PHP dependencies into Cognee memory
await cognee.remember(
    packagist_source(
        package_names=["laravel/framework", "symfony/http-foundation", "guzzlehttp/guzzle"],
        include_abandoned=False,
    ),
    dataset_name="php_ecosystem",
    primary_key="id",
    write_disposition="merge",
)
```
