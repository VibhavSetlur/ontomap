# OntoMap reference

This reference matches the installed `ontomap --help` interface. Run help in the project `.venv` before scripting against another version.

## CLI

### `map`

Choose one input source: `--sso ID`, `--ko ID`, `--input PATH`, `--text TEXT`, `--text-input PATH`, or structured `--name TEXT` with optional `--ec EC` and `--tags TAG;TAG`. `--direction {sso,ko}` is required for identifier `--input`; text/structured reaction mapping defaults to `sso`. The input formats are CSV, TSV, JSON, JSONL, Parquet, and TXT. `--id-column`, `--text-column`, and `--input-format` resolve nonstandard files.

`--method reaction` is the legacy-compatible default; `--method go-text` selects the offline GO registry. `--method-version VERSION` pins an immutable version. Common controls are `--top-k`, `--batch-size`, `--device {auto,cpu,cuda}`, `--ec-augment`, and `--quiet`.

`--output PATH` selects a writer from its extension; `--format` explicitly selects `sssom-tsv`, `json`, `jsonl`, `csv`, `tsv`, `parquet`, or `sqlite`. Omit output for JSONL stdout. SQLite contains normalized query/prediction/reaction data and a `top_n_with_meta` view. Directory outputs contain per-query JSON and a manifest.

### Other commands

| Command | Required inputs | Result |
| --- | --- | --- |
| `aggregate-tsv` | `-i INPUT -o OUTPUT` | cleaned descriptions TSV; `--provenance` writes JSONL; columns/dedup policy are configurable |
| `map-model` | `--model MODEL` | ModelSEED compound/reaction mapping; `--modelseed-dir`, `--top-k`, `--device`, `--no-network`, output SQLite/JSON |
| `cluster` | `-p PREDICTIONS -o OUTPUT` | clusters JSON/JSONL/Parquet/SQLite reaction mappings; supports `cc`, `louvain`, `label_prop`, `agglomerative`, `hdbscan` |
| `bench` | none | legacy benchmark with `--direction`, `--tiers`, `--device`, `--output-dir`, `--seed` |
| `fetch-models` | none | obtains runtime dependencies; `--force` re-acquires |
| `info` | none | installed-artifact status; `--no-smoke`, `--verify-manifest`, `--json` |
| `describe TARGET` | registry method or SQLite path | registry metadata/checksum; legacy SQLite schema README; `--method-version`, `--kind` |
| `version` | none | package version |

## Python contracts

```python
from ontomap import Pipeline, PipelineConfig, MapResult
from ontomap.api import default_registry, map_text, map_batch
```

- `PipelineConfig` configures the legacy reaction runtime (including device and runtime options).
- `Pipeline(config).map(name=..., ec=..., notes=..., tags=..., id=..., top_k=...) -> MapResult` maps one structured reaction query. At least one evidence field is required.
- `Pipeline.map_batch(...)` and `Pipeline.map_descriptions(...)` support batch legacy workflows.
- `MapResult.to_dict()` provides a JSON-friendly legacy result; `top1` is the first `(reaction_id, score)` pair or `None`.
- `default_registry()` returns the explicit local `Registry`. `resolve(method, version=None)` returns a `Bundle`; `methods()` returns metadata for every installed bundle.
- `map_text(text, method='go-text', version=None, query_id='Q1', top_k=20)` returns `MappingResult`; `map_batch(texts, ..., query_ids=None)` returns ordered results.
- `MappingResult.to_dict()` contains `query_id`, ranked `predictions` (`id`, `score`, `rank`, optional `term`), `provenance`, and `warnings`.

`MappingQuery` validates nonempty text/query IDs and positive `top_k`. A `ValidationError` has stable `.code`, `.field`, and `.to_dict()` for callers that need structured error handling.

## Schema and interoperability

Use `ontomap/schemas/mapping-result.schema.json` to validate versioned mapping-result JSON. SSSOM TSV encodes predicate buckets from confidence; CSV/TSV are tabular views; Parquet requires the declared optional dependency; SQLite is designed for downstream SQL. Preserve query IDs, rank, scores, warnings, source metadata, and method/version/artifact provenance when converting outputs.

Reaction confidence is an aid to ranking/review, not a calibrated guarantee or out-of-domain detector. GO scores are uncalibrated retrieval scores. Review mappings in their biological context.
