# Contributing to ontomap

Thanks for your interest! ontomap is research code that grew into a small
shippable package, so the contribution surface is intentionally narrow.

## Setup

```bash
git clone https://github.com/VibhavSetlur/ontomap.git
cd ontomap
pip install -e .[dev]
bash scripts/setup.sh   # downloads ~2 GB of weights + corpus + builds embeddings
```

After setup, sanity-check:

```bash
ontomap version
ontomap map --text "Enoyl-CoA hydratase (EC 4.2.1.17)"
pytest tests/
```

## What we welcome

- **Bug fixes** with a failing test that demonstrates the bug.
- **Performance improvements** with `before / after` numbers on the
  benchmarks at `tests/benchmarks/` (if you don't have access to the
  multi-gold harness, use the included Morgan-Price subset).
- **New EC corpus patches** for ModelSEED reactions with empty
  `ec_numbers`. Each patch needs:
  - reaction_id
  - proposed EC
  - 1-line evidence (KEGG R-id, BiGG label, paper DOI)
  - Append to `data/modelseed_corpus_patches.csv`; bump CHANGELOG.
- **Documentation** — especially examples that cover new domains
  (e.g. fungal metabolism, secondary metabolites).

## What we'll likely decline

- **Cross-encoder reranker swaps**. We tested 11 alternatives (workspace
  steps 32/35/37/38 in the parent project); none beats `ncbi/MedCPT-Cross-Encoder`
  at hit@20. If you have one that beats MedCPT on the multi-gold harness,
  open an issue with numbers first.
- **Adding LLM-based reranking** to the default path. ontomap is
  deliberately fast (~40 ms/query on 1× H100). LLM rerank can be added
  by a wrapper script; we won't bring it into the core path.
- **Changing the public API** (`Pipeline.map_one / map_batch / map_descriptions`,
  the `MapResult` dataclass shape) without a major-version bump.

## Style + tests

- `ruff check ontomap/` — must pass
- `pytest tests/` — must pass
- Type hints encouraged but not required
- New features add a test in `tests/` and an example in `examples/`

## Architecture compass

- `ontomap/pipeline.py` — public `Pipeline` + `MapResult` + `PipelineConfig`
- `ontomap/_frozen_runtime.py` — the runtime impl (`FrozenPipeline`)
- `ontomap/_helpers/` — bundled snapshots of the research scripts
  (step17 LoRA eval, step18 MedCPT rerank) that the runtime relies on
- `ontomap/cli.py` — the `ontomap` console script
- `ontomap/io.py` — output serializers (SSSOM-TSV, SQLite, parquet, JSON)
- `scripts/` — operator scripts (download, build, regenerate, finetune)
- `data/` — bundled artefacts (dictionaries, embeddings, corpus, patches)
- `weights/` — model checkpoints (downloaded by `scripts/setup.sh`)

## Where the research came from

ontomap was developed at Argonne (CELS) for mapping bacterial functional
annotations to ModelSEED reactions, validated against Henry's Acidovorax 3H11
gold-curated set + Morgan-Price's RAST annotations.

The full 42-step research-os campaign lives in the parent project's
`workspace/` directory (not in this repo). For why each design choice
was made — what was tested + rejected — see `CHANGELOG.md`.

## License

MIT. See `LICENSE`.

## Contact

Open an issue at github.com/VibhavSetlur/ontomap/issues
