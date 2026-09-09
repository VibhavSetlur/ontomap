# Development and testing

Run `.venv/bin/python -m pytest -q`. Tests cover registry selection, structured validation, artifact checksums,
deterministic GO ranking, GO CLI output, and the established legacy consumers. No model download or database is needed for GO tests.

The direct `pytest` executable may use a different interpreter and fail to import `ontomap`; use the module command above.
Validate ModelSEED acquisition without network using `.venv/bin/python scripts/build_corpus.py --dry-run`.
