# Contributing to OntoMap

Thank you for improving OntoMap. Keep changes focused, tested, and compatible with the public CLI/API and output contracts.

## Local workflow

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

Add or update a focused test for behavior changes. Run the relevant user-facing CLI command, `git diff --check`, and a credential/private-data scan before opening a change. Update `README.md` and the linked reference/operations docs when user-visible behavior changes.

## Boundaries

- Do not commit ModelSEED records, private/Henry workbooks or exports, private Filipe extracts, credentials, or raw restricted data.
- Preserve JSON, JSONL, SSSOM TSV, CSV, TSV, Parquet, and SQLite compatibility unless a reviewed migration explicitly changes it.
- Preserve `Pipeline`, `PipelineConfig`, `MapResult`, the versioned registry, immutable GO artifacts, and explicit rollback versions.
- New model/research artifacts require a new versioned directory, manifest/checksum, benchmark metadata, tests, and docs. Never mutate an existing artifact to alter a result.
- Use external approved storage for ModelSEED and configure it with `ONTOMAP_MODELSEED` or `--modelseed-dir`.

See `docs/DEVELOPMENT.md` for verification and `docs/OPERATIONS.md` for provenance, data, and release policy.
