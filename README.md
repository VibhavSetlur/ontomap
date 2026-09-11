# OntoMap

OntoMap is a local Python package and CLI for three related tasks:

- map SSO, KEGG Orthology (KO), or functional text to ranked ModelSEED reactions;
- map a COBRA-style model's compounds and reactions to ModelSEED identifiers; and
- map functional text to Gene Ontology (GO) terms through an immutable local registry.

It also aggregates annotation tables, writes portable mapping artifacts, clusters reaction predictions, and benchmarks the legacy reaction mapper. It runs locally; GO mapping is offline. **ModelSEED records are acquired separately and are not bundled.** Henry workbooks, exports, and private Filipe extracts are not included.

## Start here

```bash
git clone <your-hosted-ontomap-clone-url> ontomap
cd ontomap
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

The declared package metadata is the dependency authority. Use the project-local `.venv`; do not install into a shared Python environment.

### First successful run: offline GO mapping

No database or download is required for the checked-in public GO artifact:

```bash
.venv/bin/ontomap version
.venv/bin/ontomap describe go-text
.venv/bin/ontomap map --method go-text --text 'DNA-directed RNA polymerase subunit beta' --top-k 5
```

`go-text@4.0.0` is the default. Its immutable `go-height-lte-1-v1` vocabulary was prepared by applying **height <= 1 before the training split and text deduplication**. This is a training-data rule, not a runtime candidate filter. To reproduce a prior behavior deliberately, select `--method-version 2.0.0` (depth-based) or `3.0.0` (inverted-height):

```bash
.venv/bin/ontomap map --method go-text --method-version 2.0.0 --text 'DNA repair protein' --top-k 5
.venv/bin/ontomap map --method go-text --method-version 3.0.0 --text 'DNA repair protein' --top-k 5
```

Use `ontomap describe go-text --method-version VERSION` to inspect registry metadata, including the artifact checksum and preparation rule. GO retrieval scores are ranking scores, not calibrated probabilities.

### First successful run: legacy reaction mapping

The legacy reaction pipeline needs its local model assets and ModelSEED corpus. Acquire restricted upstream records outside the checkout, then point OntoMap at that location:

```bash
export ONTOMAP_MODELSEED="$HOME/.cache/ontomap/modelseed"
.venv/bin/python scripts/build_corpus.py --cache-dir "$ONTOMAP_MODELSEED" --patches
# inspect planned pinned URLs without downloading:
.venv/bin/python scripts/build_corpus.py --dry-run
.venv/bin/ontomap map --text 'Enoyl-CoA hydratase (EC 4.2.1.17)' --method reaction --top-k 5
```

`build_corpus.py` is pinned acquisition tooling; read and accept the upstream ModelSEED license before acquiring or redistributing records. The external directory must contain the tables the command obtains. Do not commit them. Runtime encoders may be fetched separately with `ontomap fetch-models`; `ontomap info --verify-manifest` verifies checked-in/bundled artifact hashes when the relevant assets are present.

**Poplar deployment note.** On Poplar, clone this repository to your project or scratch space, create the `.venv` above, install its declared dependencies, acquire ModelSEED into a permitted external cache/data location (for example `$HOME/.cache/ontomap/modelseed` or a project data mount), then set `ONTOMAP_MODELSEED` or pass `--modelseed-dir`. Keep tokens and credentials in Poplar's approved secret mechanism; neither paths nor secrets need to be hard-coded. Start with the offline GO command before requesting GPU/network resources.

## Directory map

| Path | Purpose |
| --- | --- |
| `ontomap/` | package: legacy pipeline, registry/plugins, serializers, model mapper, aggregation, clustering |
| `ontomap/artifacts/` | public-safe GO manifests, metadata, metrics, and immutable artifact payloads |
| `ontomap/schemas/` | JSON schema for versioned mapping results |
| `data/` | checked-in dictionaries and test/public fixtures; not a ModelSEED distribution |
| `weights/` | model/artifact manifest and license information |
| `examples/` | runnable legacy pipeline examples and sample inputs |
| `scripts/` | acquisition, asset, training, and maintenance utilities |
| `tests/` | regression and contract tests |
| `docs/` | reference, operations/provenance, development, and documentation transition record |

## Workflows

### Map identifiers or descriptions to reactions

```bash
# a single identifier
ontomap map --sso SSO:000000027 --top-k 20
# structured evidence: name, EC, and optional tags
ontomap map --name 'Aldehyde dehydrogenase' --ec 1.2.1.3 --tags 'putative;partial' --top-k 20
# batch IDs/descriptions: set --direction for --input, --text-column for text input
ontomap map --input examples/sample_ids.csv --id-column sso_id --direction sso -o results.sssom.tsv
```

For reaction mapping, `--ec-augment` adds EC-matched candidates to the retrieval pool. Candidate confidence fields/bands help triage but do not establish biological truth or out-of-database abstention. Preserve the input, command, method/version, and output provenance for review.

### Aggregate, map a model, cluster, or benchmark

```bash
ontomap aggregate-tsv -i annotations.tsv -o descriptions.tsv --provenance descriptions.provenance.jsonl
ontomap map-model --model model.json --modelseed-dir "$ONTOMAP_MODELSEED" -o model_mapping.sqlite
ontomap cluster -p results.sqlite -o clusters.tsv --method cc --threshold 0.3 --cap 5
ontomap bench --direction sso --tiers 10,100 --output-dir bench-out
```

`aggregate-tsv` accepts a multi-source TSV and emits cleaned descriptions plus an optional provenance JSONL. `map-model` accepts a COBRA-style JSON object with `metabolites` and `reactions`; it maps compounds then reactions, optionally using reaction-network consistency (`--no-network` disables it). `cluster` consumes OntoMap JSON/JSONL/Parquet/SQLite predictions; `cc` is the validated default. `bench` measures the bundled legacy reaction fixtures on your hardware, not universal accuracy.

## Inputs, outputs, and errors

`map` accepts one of `--sso`, `--ko`, `--input`, `--text`, `--text-input`, or structured `--name`/`--ec`. File inputs can be CSV, TSV, JSON, JSONL, Parquet, or TXT; select/override columns with `--id-column`, `--text-column`, and `--input-format`. Use stable query IDs when joining results downstream. Invalid/missing fields fail with a caller-facing validation error; use `--quiet` to suppress progress only, not errors.

Without `--output`, `map` streams JSONL. With an output path or `--format`, it writes **JSON, JSONL, SSSOM TSV, CSV, TSV, Parquet, or SQLite**. SQLite is normalized (`queries`, `predictions`, `reactions`, and `top_n_with_meta`) and receives a sibling schema README; directory output is selected by an output directory. Results carry ranked candidates, scores, rank, warnings, and method/artifact provenance. JSON mappings follow `ontomap/schemas/mapping-result.schema.json`; reaction and GO mapping targets have different domain fields.

Batch size and `--device {auto,cpu,cuda}` control resource use. Begin with a small `--top-k`/batch on a new platform, log stdout/stderr and the command, and retain warnings. A model/asset failure is actionable configuration information—do not silently substitute a method or version.

## Python API

The stable surfaces are the legacy `Pipeline`, `PipelineConfig`, and `MapResult`, plus versioned GO helpers:

```python
from ontomap import Pipeline, PipelineConfig
from ontomap.api import default_registry, map_text, map_batch

pipeline = Pipeline(PipelineConfig(device='auto'))
legacy = pipeline.map(name='Enoyl-CoA hydratase', ec='4.2.1.17', id='gene-1', top_k=5)
print(legacy.top1, legacy.to_dict())

go = map_text('DNA repair protein', method='go-text', query_id='gene-1', top_k=5)
batch = map_batch(['ATP synthase subunit A', 'DNA helicase'], method='go-text')
print(default_registry().resolve('go-text').describe(), go.to_dict(), batch[0].to_dict())
```

`MappingQuery` rejects empty text/IDs and non-positive `top_k`; `ValidationError` exposes a stable `code`, `field`, and `to_dict()`. See the complete signatures and every CLI option in [docs/REFERENCE.md](docs/REFERENCE.md).

## Configuration, provenance, and registry policy

- `ONTOMAP_MODELSEED` configures the external ModelSEED directory; `--modelseed-dir` overrides it for `map-model`.
- The registry is explicit and local: no plugin discovery or network resolution. Select a version with `--method-version` or API `version=`; never overwrite a manifest-described artifact to “roll back”.
- Manifests and checksums identify GO artifacts. Run `ontomap describe go-text` and `ontomap info --verify-manifest` as applicable. Keep source/input hashes, method versions, artifact checksums, command lines, and output files together.
- New research artifacts need a new directory, manifest, benchmark/metric metadata, immutable version, tests, and documentation; promotion must not replace an existing artifact. See [operations](docs/OPERATIONS.md).

## Command index

| Command | Use |
| --- | --- |
| `map` | identifier, text, structured, reaction, or GO mapping |
| `aggregate-tsv` | clean/aggregate multi-source annotation TSVs |
| `map-model` | map COBRA-style compounds and reactions to ModelSEED |
| `cluster` | cluster reaction-prediction artifacts |
| `bench` | benchmark legacy reaction mapping |
| `fetch-models` | acquire runtime model dependencies |
| `info` | inspect install/smoke status and optionally verify manifests |
| `describe` | inspect a registered method or generate legacy SQLite schema documentation |
| `version` | print installed package version |

Run `ontomap COMMAND --help` for the installed, authoritative interface. There is no `list` command; use `describe go-text` or the Python registry API.

## Development, security, and support

Run the checks in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). Contributions should preserve public API/output compatibility, add a focused test, and update the manual when behavior changes. Follow [CONTRIBUTING.md](CONTRIBUTING.md).

Do not put credentials, private workbooks, raw restricted data, or personally sensitive annotations in issues, examples, fixtures, or outputs. Treat mapping results as decision support requiring domain review. Licensing, artifact verification, restricted-data handling, and the documentation transition are documented in [docs/OPERATIONS.md](docs/OPERATIONS.md). AI users should follow [AGENTS.md](AGENTS.md).
