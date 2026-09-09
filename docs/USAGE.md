# Usage guide

OntoMap has two workflows. The legacy reaction/model workflow maps SSO/KO identifiers or functional descriptions to ModelSEED reactions. The registry workflow maps text to GO terms. They share the `map` CLI and output writer, but use different methods and result targets.

## Legacy reaction/model workflow

The default method is `reaction`; existing calls remain valid:

```bash
ontomap map --sso SSO:000000027 --top-k 5
ontomap map --ko K10046 --top-k 5
ontomap map --input ids.csv --direction sso --output reactions.sssom.tsv
ontomap map --text 'Enoyl-CoA hydratase (EC 4.2.1.17)' --method reaction --output reactions.json
```

For structured annotations, `--name`, `--ec`, and optional semicolon-delimited `--tags` form one text query. For batches, use `--text-input FILE`; `--text-column` and `--id-column` select columns. Input formats are CSV, TSV, JSON, JSONL, Parquet, and TXT. `--direction sso` is the default for text; use `--direction ko` for KO-oriented data. `--ec-augment`, `--device`, `--top-k`, `--batch-size`, and `--quiet` control the legacy path.

Acquire ModelSEED separately as described in [installation](INSTALL.md#external-modelseed-data); it is not bundled.

## Registry text-to-GO workflow

GO is an explicit method on `map`, not a separate CLI command. It accepts text, structured `--name`/`--ec`, or `--text-input`:

```bash
ontomap map --method go-text --text 'DNA repair helicase' --top-k 10
ontomap map --method go-text --text-input annotations.tsv \
  --id-column gene --text-column product --method-version 1.0.0 --output go.parquet
```

Inspect locally registered methods and their immutable versions before selecting one:

```bash
ontomap list
ontomap describe go-text --method-version 1.0.0
```

The bundled GO method is `go-text@1.0.0`; compatibility reaction mapping is `reaction@legacy-1`. Results retain method/version provenance. Promote a research artifact by authoring a new immutable directory, manifest, and version; roll back by selecting a former version. These are artifact/version authoring and explicit selection practices, not CLI lifecycle commands. `list` is available from the source tree or a current editable installation. GO retrieval scores are not calibrated probabilities; use ranked candidates and provenance for review rather than an automatic biological conclusion.

## Outputs, confidence, and directories

Use `--output` with `.json`, `.jsonl`, `.sssom.tsv`, `.csv`, `.tsv`, `.parquet`, or `.sqlite`, or select explicitly with `--format`. A directory output creates per-query JSON plus `manifest.json`.

| Output | Typical use |
|---|---|
| JSON / JSONL | rich records / streaming |
| SSSOM TSV | ontology mapping interchange |
| CSV / TSV | flat ranked rows |
| Parquet | analytics pipelines |
| SQLite | queryable local deliverable |
| directory | many independent query records plus manifest |

Reaction confidence fields and calibration are workflow-specific; do not apply reaction thresholds to GO results. Preserve result provenance and source/input licenses in downstream processing.

## Aggregate, model mapping, bench, and clustering

`aggregate-tsv` prepares redundant annotation tables and can write a provenance JSONL sidecar:

```bash
ontomap aggregate-tsv --input annotations.tsv --output descriptions.tsv \
  --provenance descriptions.provenance.jsonl --dedup global
ontomap map --text-input descriptions.tsv --id-column id --text-column description --output predictions.json
```

Additional command options are concisely listed in [API and CLI](API_CLI.md#cli). Common invocations are:

```bash
ontomap map-model --model model.json --format sqlite
ontomap bench --direction both --output-dir benchmark_output
ontomap cluster --predictions predictions.json --output clusters.tsv
ontomap info --json
ontomap fetch-models --force
ontomap version
```

For full API signatures, see [API and CLI](API_CLI.md). For a transparent fixture walkthrough rather than unavailable private data, see [Acidovorax fixture walkthrough](REAL_WORLD_ACIDOVORAX.md).
