# OntoMap

OntoMap supports two local workflows: the unchanged **legacy reaction/model** mapper (SSO/KO or functional descriptions → ModelSEED reactions) and the **registry text-to-GO** mapper (text → GO terms). Choose the method explicitly when using text.

## Prerequisites and install

Python 3.10–3.12 and `pip` are required. From this project directory:

```bash
python -m venv .venv
. .venv/bin/activate                 # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .
# optional: python -m pip install -e '.[gpu,sssom]'
ontomap version
```

See [installation details](docs/INSTALL.md). `ontomap fetch-models` downloads runtime model dependencies when needed; `ontomap info --verify-manifest` verifies bundled-weight hashes.

## Two five-minute examples

Legacy reaction mapping is still the default:

```bash
ontomap map --sso SSO:000000027 --top-k 5
ontomap map --text 'Enoyl-CoA hydratase (EC 4.2.1.17)' --method reaction --output reactions.json
```

GO mapping is the `map` command with `--method go-text`, not a separate command:

```bash
ontomap map --method go-text --text 'DNA repair helicase' --top-k 5
ontomap map --method go-text --text-input annotations.tsv \
  --id-column gene --text-column product --output go.jsonl
```

Both commands print one JSON result per query without `--output`. Batch input formats are CSV, TSV, JSON, JSONL, Parquet, or TXT. Output can be JSON, JSONL, SSSOM TSV, CSV, TSV, Parquet, SQLite, or a directory (one JSON file per query plus a manifest); choose by extension or use `--format`.

## Common commands

```bash
ontomap list                              # registered method/version pairs
ontomap describe go-text --method-version 4.0.0
ontomap info --json
ontomap fetch-models
ontomap bench --help
ontomap cluster --predictions results.json --output clusters.tsv
ontomap aggregate-tsv --input raw.tsv --output clean.tsv --provenance clean.jsonl
```

Use `ontomap map --help` for exact options: `--sso`, `--ko`, `--input`, `--text`, and `--text-input` are mutually exclusive; `--method {reaction,go-text}`, `--method-version`, `--direction`, `--top-k`, `--batch-size`, `--device`, and output controls apply as documented in [API and CLI](docs/API_CLI.md).

## Python APIs

```python
from ontomap.pipeline import Pipeline
legacy = Pipeline.from_pretrained(direction='sso', device='auto')
reaction = legacy.map_one('SSO:000000027', top_k=5)

from ontomap.api import map_text, map_batch
one_go = map_text('DNA repair helicase', method='go-text')  # corrected 4.0.0 default
many_go = map_batch(['DNA repair helicase'], method='go-text', version='4.0.0')
```

Legacy methods and serializers are detailed in [API and CLI](docs/API_CLI.md). Results include ranked mappings and method/version provenance. Reaction results include reaction-oriented fields; GO results are GO mappings. GO scores are retrieval scores, not calibrated probabilities. For confidence, clustering, model mapping, benchmarking, and output details, see [usage](docs/USAGE.md).

## External ModelSEED corpus

ModelSEED records are **not bundled**. Acquire them only for reaction/model mapping:

```bash
.venv/bin/python scripts/build_corpus.py --cache-dir data/modelseed_corpus
.venv/bin/python scripts/build_corpus.py --dry-run
```

The acquisition script pins commit `194ac8afe48f8a606c0dd07ba3c7af10c02ba2fd`, records per-file SHA-256 values in `manifest.json`, and records the upstream [CC BY 4.0 license](https://raw.githubusercontent.com/ModelSEED/ModelSEEDDatabase/master/LICENSE). Select an acquired corpus with `--modelseed-dir PATH` or `ONTOMAP_MODELSEED=PATH`; inspect the manifest/checksums before relying on a cache. GO inference remains local and does not require this corpus.

## Compatibility, provenance, and security

`reaction@legacy-1` remains available for compatibility. The default `go-text@4.0.0` uses immutable `filipe-go-height-lte-1-dedup-v1`: GO **height** is distance to the furthest descendant, and `height <= 1` was retained before training and text-deduplicated splitting; terms with `height >= 2` were excluded. The runtime never height-filters candidates—the model vocabulary is already the filtered training vocabulary. For explicit rollback, select the prior depth model `go-text@2.0.0` or the prior inverted-height model `go-text@3.0.0`; their weights and manifests remain immutable. `list` and `describe` reveal versions and checksums. Research promotion means authoring a new artifact directory, manifest, and version; roll back by selecting a prior version—never overwrite a manifest-described artifact. Results include method, model, artifact, filter, benchmark, and runtime provenance. GO scores are uncalibrated retrieval scores and benchmark results do not transfer to Henry. See [compatibility](docs/COMPATIBILITY_MIGRATION.md) and [artifact security](docs/ARTIFACTS_SECURITY_PROVENANCE.md).

## Feature matrix

| Capability | Legacy reaction/model | Registry GO text |
|---|---|---|
| Inputs | SSO/KO IDs, descriptions, structured name/EC | text or text files |
| CLI | `map --method reaction` (default) | `map --method go-text --text` / `--text-input` |
| Python API | `Pipeline` | `map_text`, `map_batch` |
| Method version | legacy compatibility method | `go-text@4.0.0` default (`go-text@2.0.0` depth and `@3.0.0` inverted-height rollback) |
| External ModelSEED corpus | optional/acquire-only | not required |
| Batch/output formats | supported | supported via `map` output writer |

See [examples](examples/README.md), [usage](docs/USAGE.md), and [API/CLI](docs/API_CLI.md).
