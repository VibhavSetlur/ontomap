# OntoMap

OntoMap provides local, versioned ontology mapping inference. It retains the reaction `Pipeline`/CLI and introduces a
self-contained Filipe text-to-GO plugin with immutable checksummed artifacts and provenance-bearing results.

## Quick start

```bash
ontomap map --method go-text --text "DNA repair helicase" --top-k 20
```

New API users should call `ontomap.api.map_text`; legacy users can continue using `Pipeline` and `ontomap map` unchanged.
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/API_CLI.md](docs/API_CLI.md),
[docs/PLUGIN_AUTHORING.md](docs/PLUGIN_AUTHORING.md), [docs/ARTIFACTS_SECURITY_PROVENANCE.md](docs/ARTIFACTS_SECURITY_PROVENANCE.md),
[docs/COMPATIBILITY_MIGRATION.md](docs/COMPATIBILITY_MIGRATION.md), and [docs/DEVELOPMENT_TESTING.md](docs/DEVELOPMENT_TESTING.md).

The bundled GO model uses word and character TF-IDF centroid cosine retrieval. Its scores are descriptive, not calibrated probabilities.
The accepted external benchmark is kept separate under `ontomap/benchmarks`; it records 130,061 entities, 104,032/26,029 train/test,
4,588 candidates, no entity overlap, top-1/5/20/100 .7989/.9218/.9502/.9705, MRR .8570, and coverage .9856.

## ModelSEED external corpus

ModelSEED records are **not packaged**. Acquire a reproducible ignored cache only when reaction/model mapping needs it:

```bash
.venv/bin/python scripts/build_corpus.py --cache-dir data/modelseed_corpus
```

The fetcher pins `194ac8afe48f8a606c0dd07ba3c7af10c02ba2fd`, writes per-file SHA-256 values to
`manifest.json`, and records the upstream [CC BY 4.0 license](https://raw.githubusercontent.com/ModelSEED/ModelSEEDDatabase/master/LICENSE).
It downloads external records only; a cache's presence must not be interpreted as proof that it matches the pin. Preview URLs without network access:

```bash
.venv/bin/python scripts/build_corpus.py --dry-run
```

Pass `--modelseed-dir PATH` or set `ONTOMAP_MODELSEED=PATH` to explicitly select an acquired corpus. GO inference and its tests remain offline.
