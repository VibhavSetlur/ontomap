# Operations, provenance, and data handling

## Assets and ModelSEED

OntoMap is self-contained for code, package metadata, public-safe GO artifacts/manifests, examples, tests, and acquisition tooling. It intentionally does **not** bundle the ModelSEED corpus. Upstream records and their license/redistribution conditions remain external.

Acquire ModelSEED only into an approved external directory and configure it without embedding credentials:

```bash
export ONTOMAP_MODELSEED="$HOME/.cache/ontomap/modelseed"
.venv/bin/python scripts/build_corpus.py --cache-dir "$ONTOMAP_MODELSEED" --patches
.venv/bin/python scripts/build_corpus.py --dry-run
```

For model mapping, either export `ONTOMAP_MODELSEED` or pass `--modelseed-dir PATH`. On Poplar, choose an approved project/user data mount or cache, never a repository path for restricted data. Store access tokens only in the platform's secret facility. `scripts/setup.sh` is an operator convenience script that may download runtime assets and acquire data; inspect it and use explicit external paths before running it.

See `weights/LICENSES.md` and upstream ModelSEED licensing before redistribution. Do not claim bundled access to Henry data, Henry workbook/export, or private Filipe extracts.

## Registry, artifacts, and rollback

The registry contains local, explicit implementations. `go-text@4.0.0` is the default and has artifact version `filipe-go-height-lte-1-dedup-v1`. It used a height<=1 training-data selection before splitting/deduplication; runtime mapping does not filter candidates by height. `go-text@2.0.0` and `go-text@3.0.0` are explicit rollback selections, respectively depth-based and inverted-height training artifacts.

Inspect rather than infer metadata:

```bash
.venv/bin/ontomap describe go-text
.venv/bin/ontomap describe go-text --method-version 4.0.0
.venv/bin/ontomap info --verify-manifest
```

Artifacts are immutable units: directory, manifest, checksum, training/preparation metadata, and metric metadata. A research update must create a new artifact directory and method version, validate it with tests and a documented benchmark, then make it default only through reviewed code/metadata. Roll back by selecting a prior version—never by overwriting a manifest or weight file. Retain input hashes, commands, package version, method/version, artifact checksum, output, and warnings with every operational result.

## Security and responsible use

Keep credentials, private datasets, raw restricted records, and sensitive annotations out of the repository, issue tracker, examples, and generated artifacts. Scan before sharing:

```bash
git diff --check
rg -n --hidden -g '!\.git/**' -i '(api[_-]?key|secret|password|token)' .
```

Review scanner hits: documentation may contain safe variable names, but no value belongs in source control. Mapping outputs are ranked suggestions, not clinical, regulatory, or biological proof; independently review low-confidence, novel, and out-of-database cases.

## Documentation transition

The current manual replaces historical installation, usage, API, migration, benchmark, validation, architecture, plugin, case-study, fine-tuning, setup, and release-note fragments. Their operational content is consolidated in `README.md`, `docs/REFERENCE.md`, `docs/OPERATIONS.md`, `docs/DEVELOPMENT.md`, `CONTRIBUTING.md`, and `weights/LICENSES.md`. Obsolete Claude-specific guidance and stale command references were removed; no functional package code, tests, examples, schemas, manifests, or acquisition tooling was removed.
