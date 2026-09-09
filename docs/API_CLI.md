# API and CLI

## Legacy reaction API

The established `Pipeline` API remains supported:

```python
from ontomap.pipeline import Pipeline
pipeline = Pipeline.from_pretrained(direction='sso', device='auto', weights_dir=None)
pipeline.map_one('SSO:000000027', top_k=None)
pipeline.map_batch(['SSO:000000027'], top_k=None, batch_size=64, verbose=True)
pipeline.map_descriptions(['Enoyl-CoA hydratase'], ids=None, top_k=None, batch_size=64, verbose=True)
pipeline.map(name='Enoyl-CoA hydratase', ec='4.2.1.17', notes=None,
             tags=None, id=None, top_k=None, verbose=False)
```

Exact signatures (apart from `self`) are:

- `Pipeline.from_pretrained(direction='sso', device='auto', weights_dir=None, **kwargs)`
- `map_one(query_id, top_k=None)`
- `map_batch(query_ids, top_k=None, batch_size=64, verbose=True)`
- `map_descriptions(descriptions, ids=None, top_k=None, batch_size=64, verbose=True)`
- `map(name=None, ec=None, notes=None, tags=None, id=None, top_k=None, verbose=False)`

For annotation-table preparation, use:

```python
from pathlib import Path
from ontomap.aggregate import aggregate_annotation_tsv
aggregate_annotation_tsv(Path('raw.tsv'), Path('clean.tsv'), provenance_path=Path('clean.jsonl'),
                         dedup_mode='per-gene', drop_trivial=True, gene_column='gene',
                         source_column='source', description_column='description',
                         ontology_column='ontology_term', reactions_column='reactions')
```

Its signature is `aggregate_annotation_tsv(input_path, output_path, provenance_path=None, dedup_mode='per-gene', drop_trivial=True, gene_column='gene', source_column='source', description_column='description', ontology_column='ontology_term', reactions_column='reactions')` and it returns `(n_output_rows, n_unique_genes, n_provenance_records)`.

## Registry text-to-GO API

```python
from ontomap.api import map_text, map_batch
result = map_text('DNA repair helicase', method='go-text', version='1.0.0', query_id='gene-1', top_k=20)
results = map_batch(['DNA repair helicase', 'ATP synthase assembly'],
                    method='go-text', version='1.0.0', query_ids=['gene-1', 'gene-2'], top_k=20)
```

`map_batch` preserves input order and generates `Q1`, `Q2`, … when IDs are omitted. The registry resolves the selected local method/version and returns provenance-bearing results. `go-text@2.0.0` accepts text by default; select `go-text@1.0.0` explicitly for rollback; `reaction@legacy-1` is the compatibility method. Promote research artifacts by adding a new immutable directory/manifest/version, and roll back by selecting a prior version; these are authoring and selection practices, not CLI lifecycle commands.

## CLI

`map` has mutually exclusive inputs: `--sso ID`, `--ko ID`, `--input FILE`, `--text TEXT`, `--text-input FILE`, or structured `--name`/`--ec` (with optional `--tags`). The legacy default is `--method reaction`; GO requires `--method go-text` and text input:

```bash
# legacy single and batch
ontomap map --sso SSO:000000027 --top-k 5
ontomap map --input ids.csv --direction sso --output reactions.sssom.tsv
# GO single and batch
ontomap map --method go-text --text 'DNA repair helicase' --top-k 20
ontomap map --method go-text --text-input genes.tsv --text-column product --id-column gene \
  --method-version 1.0.0 --output go.jsonl
```

`map` options include `--direction {sso,ko}`, `--method {reaction,go-text}`, `--method-version`, `--text-column`, `--id-column`, `--text-id`, `--input-format {csv,tsv,json,jsonl,parquet,txt}`, `--output`, `--format {sssom-tsv,json,jsonl,csv,tsv,parquet,sqlite}`, `--top-k`, `--batch-size`, `--device`, `--ec-augment`, and `--quiet`.

Other command synopses (brackets mark optional arguments) are:

```text
aggregate-tsv --input/-i INPUT --output/-o OUTPUT [--provenance PATH] [--dedup {per-gene,global}] [--keep-trivial] [--gene-column COL] [--source-column COL] [--description-column COL] [--ontology-column COL] [--reactions-column COL]
map-model --model MODEL [--output/-o PATH] [--format/-f {sqlite,json}] [--modelseed-dir PATH] [--top-k/-k N] [--device DEVICE] [--no-network] [--quiet/-q]
bench [--direction {sso,ko,both}] [--tiers CSV] [--device DEVICE] [--output-dir PATH] [--seed N]
fetch-models [--force]
info [--no-smoke] [--verify-manifest] [--json]
list
describe TARGET [--method-version VERSION] [--kind {auto,annotated,model,core}]
cluster --predictions/-p PATH --output/-o PATH [--method/-m METHOD] [--threshold/-t FLOAT] [--cap N] [--topk/-k N] [--inject-sqlite PATH] [--quiet/-q]
version
```

`list` is available from the source tree or a current editable installation. Use `ontomap COMMAND --help` for defaults and command descriptions.

## Results and serializers

Without `--output`, `map` emits JSON objects on stdout. File writers select JSON, JSONL, SSSOM TSV, CSV, TSV, Parquet, or SQLite by extension (or `--format`). An output directory writes per-query JSON files and a manifest. Preserve query IDs, ranked mappings, scores, method/version provenance, and source input metadata; reaction and GO result schemas differ by mapping target. See [usage](USAGE.md) for format selection and operational guidance.
