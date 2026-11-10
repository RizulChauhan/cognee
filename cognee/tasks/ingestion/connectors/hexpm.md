# Hex.pm (Elixir & Erlang Package Registry) Data Source Connector

The Hex.pm connector ingests Elixir and Erlang package metadata, licenses, versions, retirement notices, and repository links from the official Hex.pm API (`hex.pm/api`) into Cognee graph memory.

---

## Capabilities
- **Direct API Access**: Connects to `https://hex.pm/api/packages/{name}` with zero credentials or keys required.
- **Retirement Intelligence**: Detects retired packages and flags reasons/migration advisories.
- **Tombstones (`_deleted`)**: Flags retired packages with `_deleted: True` to automatically clear orphaned dependencies from memory.

---

## Python Usage

```python
import cognee
from cognee.tasks.ingestion.connectors import hexpm_source

# Ingest Elixir ecosystem dependencies into Cognee memory
await cognee.remember(
    hexpm_source(
        package_names=["phoenix", "ecto", "plug", "jason"],
        include_retired=False,
    ),
    dataset_name="elixir_ecosystem",
    primary_key="id",
    write_disposition="merge",
)
```
