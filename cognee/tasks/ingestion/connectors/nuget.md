# NuGet v3 (.NET Package Registry) Data Source Connector

The NuGet connector ingests .NET package metadata, target-framework dependency groups, deprecation notices, and known security vulnerability advisories from the official NuGet v3 API (`api.nuget.org`) into Cognee graph memory.

---

## Capabilities
- **Dynamic Service Index**: Automatically discovers `RegistrationsBaseUrl` and `SearchQueryService` dynamically from `https://api.nuget.org/v3/index.json`.
- **Target Framework Dependency Mapping**: Records dependencies across .NET Standard, .NET Framework, and modern .NET 8.0/9.0.
- **Deprecation Intelligence**: Captures deprecation reasons, migration notes, and Microsoft-recommended alternate packages.
- **Security Vulnerability Audits**: Ingests GHSA and CVE security advisory links and severity scores into graph nodes.
- **Tombstones (`_deleted`)**: Automatically flags unlisted or removed packages so stale dependencies are purged from Cognee on subsequent syncs.
- **Zero API Keys**: Connects to the public, free NuGet v3 registry with no accounts or secrets required.

---

## Python Usage

```python
import cognee
from cognee.tasks.ingestion.connectors import nuget_source

# Ingest specific dependencies into Cognee memory
await cognee.remember(
    nuget_source(
        package_ids=["Newtonsoft.Json", "Microsoft.Extensions.Logging", "Serilog"],
        include_unlisted=False,
    ),
    dataset_name="dotnet_ecosystem",
    primary_key="id",
    write_disposition="merge",
)

# Search Cognee memory
results = await cognee.search("Which packages are deprecated and what replacements are recommended?")
```
