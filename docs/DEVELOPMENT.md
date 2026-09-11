# Development and testing

Use a fresh project-local environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Run the full suite and package checks from the repository root:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m build
.venv/bin/twine check dist/*
.venv/bin/ontomap --help
.venv/bin/ontomap map --help
.venv/bin/ontomap describe go-text
.venv/bin/python scripts/build_corpus.py --dry-run
```

Test a representative offline GO mapping and the Python API after changing public documentation or registry behavior:

```bash
.venv/bin/ontomap map --method go-text --text 'DNA repair protein' --top-k 3
.venv/bin/python -c "from ontomap.api import map_text; print(map_text('DNA repair protein').to_dict())"
```

`map-model`, legacy reaction mapping, `bench`, and full `info` may require local runtime assets and an external ModelSEED directory; use their help output and configured approved paths. Do not substitute private data or run Henry workflows as a smoke test.

Before a change is proposed, run `git diff --check`, review the diff, run a secret/private-data scan, and ensure every README command was exercised or is directly represented by a tested CLI contract. Add focused tests for behavior changes. Preserve all serializers and formats (JSON, JSONL, SSSOM TSV, CSV, TSV, Parquet, SQLite), public API compatibility, registry rollback versions, and artifact provenance.
