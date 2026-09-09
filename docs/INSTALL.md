# Installation

OntoMap requires Python 3.10–3.12. Install into a project-local virtual environment from the repository root:

```bash
python -m venv .venv
. .venv/bin/activate                 # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .
ontomap version
```

Optional extras are `.[gpu]` for FAISS GPU, `.[sssom]` for SSSOM tooling, `.[dev]` for development tools, and `.[bench]` for benchmark plotting:

```bash
python -m pip install -e '.[gpu,sssom]'
```

Check the installation and local model state:

```bash
ontomap info
ontomap info --verify-manifest
ontomap fetch-models
```

`fetch-models` downloads required runtime dependencies when they are not already available. Verify model manifests before use in controlled environments.

## External ModelSEED data

Reaction/model mapping can use an external ModelSEED corpus. It is not bundled. Acquire it deliberately and retain its manifest:

```bash
.venv/bin/python scripts/build_corpus.py --cache-dir data/modelseed_corpus
.venv/bin/python scripts/build_corpus.py --dry-run
```

The script pins `194ac8afe48f8a606c0dd07ba3c7af10c02ba2fd`, writes SHA-256 values to `manifest.json`, and records the upstream [CC BY 4.0 license](https://raw.githubusercontent.com/ModelSEED/ModelSEEDDatabase/master/LICENSE). Point OntoMap at an acquired copy with `--modelseed-dir PATH` or `ONTOMAP_MODELSEED=PATH`. Text-to-GO mapping does not require ModelSEED.

Next, run the [two workflow quick starts](../README.md#two-five-minute-examples) or location-neutral [examples](../examples/README.md).
