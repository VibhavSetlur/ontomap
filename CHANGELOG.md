# Changelog

All notable changes to ontomap are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.8.3] — 2026-06-30

**Input-robustness fix for free-text mapping.** `Pipeline.map_descriptions` crashed with
`TypeError: expected string or bytes-like object, got 'float'` when a description was
non-string — e.g. a `None` or a `NaN` float coming straight from a pandas column, which is
common in real annotation dumps (TRANSYT / DRAM2 / BAKTA exports). Surfaced while
preparing resolved descriptors for the 48-genome council augmentation.

### Fixed
- **`Pipeline.map_descriptions`**: coerces non-string descriptions at the API boundary
  (`None` → `""`, other non-str → `str(...)`) so no downstream regex/encoder path receives
  a non-string.
- **`_frozen_runtime._free_text_metadata`** and **`multi_axis.clean_name`**: defensive
  string coercion (defense-in-depth for the same class of bug).
- New regression test `tests/test_input_robustness.py::test_non_string_descriptions_do_not_crash`.

## [1.8.2] — 2026-06-29

**Clustering scalability fix — required for the full-genome run.** The 113,006-description
all-genome set has a giant reaction-hub component (~85k descriptions transitively linked through a
handful of very common reactions). The previous clustering hung on it (the adjacency builder
materialised ~10^9 candidate pairs and the cap-split re-ran connected components on the whole blob
at every threshold step). No change to results on the validated 49k set; the cap is still always
honoured.

### Fixed
- **`_build_adjacency`**: replaced the global all-pairs `checked` set with a per-item co-occurrence
  Counter plus a **shared-reaction prefilter** (`_min_shared_for_threshold`) — a pair can only reach
  Jaccard ≥ t if it shares enough reactions, so the >99% of hub pairs that can't are skipped before
  any Jaccard is computed. Memory is now bounded by per-item candidates, not the global pair space.
- **`_enforce_cap`**: oversized pieces now use an **accelerated threshold schedule** (geometric jump
  toward `max_t` instead of crawling by `step`) and a deterministic size-cap fallback once near the
  ceiling, so an irreducible dense hub finishes in bounded time instead of looping. Full 113k set
  now clusters in ~6 min.

## [1.8.1] — 2026-06-26

**Production hardening for the full-genome run.** No behaviour change to the validated pipeline —
this locks robust defaults and makes the I/O fail loudly + clearly instead of cryptically, ahead of
running the final 48-genome annotation parquet (filter non-metabolic [upstream] → `ontomap map` →
`ontomap cluster`).

### Changed
- **`ontomap map --top-k` default 10 → 20** — a default batch run now already emits the validated
  production depth and satisfies downstream `ontomap cluster` (top-20) without silent truncation.
  Ad-hoc single-query use is unaffected (pass `-k` to override).

### Hardened (clearer errors, no silent failures)
- **Description readers** (parquet / csv / tsv / jsonl): an explicit `--text-column` /
  `--id-column` that doesn't exist now raises a clear error listing the available columns
  (was a cryptic `KeyError`). Empty inputs return `([], [])` instead of crashing.
- **`load_reaction_sets_from_predictions`**: missing file → `FileNotFoundError`; a SQLite without a
  `predictions` table or a parquet missing `query_id/rank/reaction_id` → a clear `ValueError`
  naming the gap. **Added `.parquet` predictions support** (query_id, rank, reaction_id).

## [1.8.0] — 2026-06-26

**Selectable clustering algorithms (NEW, additive).** `cluster_reaction_sets` and the
`ontomap cluster` CLI now take a `method=` / `--method` argument to choose how each natural
Jaccard component is refined into sub-clusters. Added after a 7-way algorithm bake-off on the
real 49,183-description top-20 reaction sets (workspace step 55).

### Added
- **`method` parameter** on `cluster_reaction_sets(...)`, `cluster_result_from_results(...)`,
  and `ontomap cluster --method`. Choices (`ontomap.CLUSTER_METHODS`):
  - `cc` (default) — connected components + hierarchical tighten-split. Best stability,
    simplest, dependency-free, and the only method that scales to the data's giant
    ~30k-node reaction-hub component. **Recommended production default.**
  - `louvain`, `label_prop` — graph community detection (needs `networkx`); slightly more
    aggressive merging.
  - `agglomerative`, `hdbscan` — pairwise-distance methods (need `scipy` / `scikit-learn`);
    auto-fall-back to `cc` on components above `cluster._MAX_DENSE` (the O(m²) distance
    matrix cannot be built on the hub).
- `CLUSTER_METHODS` exported from the package root.
- `ClusterResult.params` now records `algorithm` for provenance.

### Findings (step 55 bake-off, 49,183 descriptions, top-20, cap=5)
- All 7 algorithms land within **~1.6%** on cluster count, multi-member count, cohesion, and
  stability. Method choice is second-order to threshold + cap.
- `cc` has the best stability (ARI 0.793) and ties `hdbscan` for best cohesion (~0.625);
  `louvain`/`greedy`/`dyncut` merge slightly more at marginally lower cohesion + stability.
- Data contains one 30,553-node reaction-hub component; only graph/CC methods scale to it.

### Tests
- `tests/test_cluster_methods.py` — every method runs, respects the cap, groups obvious
  synonyms, records provenance; invalid method + `cap<1` raise.

## [1.7.0] — 2026-06-25

**Pre-council clustering (NEW, additive).** Adds the upstream clustering stage for the
48-genome annotation pipeline: group function descriptions whose ontomap ModelSEED
reaction predictions overlap, so José's LLM council can run once per small cluster instead
of once per description. Reaction-output Jaccard connected-components with a hard size cap
enforced by hierarchical sub-clustering — the method selected and hardened in a five-way
bake-off + robustness study (see workspace step 52). Nothing in the existing map / map-model
/ aggregate paths changes.

### Added
- **`ontomap/cluster.py`** — `cluster_reaction_sets(reaction_sets, threshold=0.3, cap=5,
  topk=10)` groups queries by Jaccard overlap of their top-k reaction predictions; any
  component above `cap` is split by hierarchical threshold-tightening (never random
  batching). Each cluster gets a stable `uuid5` id. `cluster_embeddings(...)` is provided
  as a documented comparator only (k-means cannot respect the small cap). `ClusterResult`
  dataclass carries assignments + per-cluster size/cohesion/representative.
- **`ontomap cluster` CLI** — clusters an ontomap predictions artefact (`.sqlite`/`.json`/
  `.jsonl`) and writes a cluster-UUID table (`.parquet`/`.tsv`/`.csv`/`.json`). `--threshold`,
  `--cap`, `--topk` knobs; `--inject-sqlite` also writes the clusters into an existing
  deliverable DB.
- **SQLite schema** — `write_sqlite` / `write_annotated_sqlite` accept `cluster_result=` and
  add `clusters` + `cluster_members` tables and a `cluster_overview` view.
- Public API: `cluster_reaction_sets`, `cluster_embeddings`, `ClusterResult` exported from
  the package root.

### Validated
- On the real Acidovorax 3H11 deliverable (8,473 descriptions × top-100): 5,489 clusters,
  zero above the cap (max size 5), within-cluster cohesion 0.64, assignment stability ARI
  0.877 under prediction perturbation, and biologically coherent synonym/subunit families.
  Embedding/k-means baselines leaked 47–79 % of items into clusters up to size ~1,850–3,000.

## [1.6.1] — 2026-06-25

**Truly self-contained from a `git clone`.** A user hit
`need: SSO LoRA adapter + target_sapbert.npz` running the reaction pipeline from
a fresh clone. Root cause: the assets that make capability 2 work were
`.gitignore`d (so absent from any clone) AND the regeneration path was broken in
several places. This release makes a clone + `bash scripts/setup.sh` reconstruct
**every** asset with no maintainer hand-off, and the docs no longer claim the
LoRA/dictionaries are "not public".

### Fixed — fresh clone was non-functional for capability 2
- **`ontomap/_helpers/ontomap_lib/*` were symlinks** into a sibling `src/` tree
  that doesn't exist in a clone (dangling links → all reaction-pipeline imports
  broke). De-referenced into real committed files.
- **`ontomap_lib/data.py`** read dead paths (`data/ground-truth/`,
  `data/raw/modelseed/`). Now resolves the real bundled layout
  (`data/dictionaries/`, `data/modelseed_corpus/`), honours `$ONTOMAP_HOME`, and
  works standalone (not just under the runtime's monkey-patch).
- **`_helpers/step17_evaluate.py`** had a hardcoded `/scratch/vsetlur/...` root +
  workspace-only embedding/swept-weight paths. Now derived from the package
  location with bundled-layout defaults.
- **`scripts/build_corpus.py`** fetched only `reactions.tsv`/`compounds.tsv`,
  not the `Aliases/Unique_ModelSEED_*.txt` tables the multi-axis render +
  `regen_embeddings.py` require. Now downloads them too.

### Added — reproducible LoRA + one-command bootstrap
- **`scripts/train_lora_from_splits.py`** reproduces both LoRA adapters from the
  bundled `data/splits/` with the frozen recipe — the adapters are no longer a
  "request from the maintainer" artifact. Verified to reproduce the published
  top-1 calls (e.g. Enoyl-CoA hydratase → rxn02167).
- **`scripts/setup.sh`** rewritten into one idempotent bootstrap (install →
  encoders → corpus → embeddings → LoRA → verify) that handles both a fresh
  clone and a populated checkout; `--skip-reaction-pipeline` for capability 1
  only.

### Changed — commit the small gold inputs
- `.gitignore` now **tracks** `weights/lora/`, `data/dictionaries/`, and
  `data/splits/` (~34 MB total) so the clone is self-contained, while keeping the
  large regenerable binaries (encoders, embeddings npz, ModelSEED corpus) out of
  git.
- Docs (`README`, `INSTALL`, `CLAUDE.md`, `SETUP_ASSETS.md`) updated: both
  capabilities run from a clone; removed "not public / broken symlinks / request
  from maintainer" language.

### Verified
- Simulated a gitignore-accurate fresh clone, ran `setup.sh`: 16/16 artifacts
  present, 5/5 assets healthy, 28 smoke tests pass, both capabilities produce
  correct mappings. `regen_embeddings.py` reproduces a bit-identical cache.

## [1.6.0] — 2026-06-24

Self-contained, deletion-resilient, and self-documenting. Motivated by a
deletion that emptied `data/embeddings/` (the runtime's base SapBERT cache)
while a stale symlink lingered — the tool's data layer had been a web of
symlinks pointing out of the repo into volatile workspace/inputs dirs.

### Fixed — embedding regeneration wrote the wrong npz keys
- **`scripts/regen_embeddings.py` wrote keys `name/ec/equation/pathway`**, but
  the runtime loader (`step17_evaluate.load_base_cache`) reads
  `name_emb/ec_emb/eq_emb/pw_emb/ecs_raw`. A regenerated cache loaded fine in
  the script but **crashed at `ontomap map` time** — the documented recovery
  path was broken. The target + source writers now emit the exact runtime keys
  (incl. `ecs_raw`), and a **post-write self-check** reloads and validates the
  six keys + row-alignment so the format can never silently regress.
- Fixed `SETUP_ASSETS.md` references to scripts that don't exist
  (`link_weights.py`, `encode_corpus.py`) → point at the real
  `download_models.py` / `regen_embeddings.py`; corrected the regen invocation.

### Added — self-contained assets (deletion resilience)
- All non-regenerable assets (LoRA adapters, SSO/KO dictionaries, splits,
  swept weights) and the runtime embedding cache are now **vendored as real
  files** in a maintainer checkout instead of symlinks into `workspace/` /
  `inputs/`. The tool survives a wipe of those dirs. Assets stay gitignored, so
  the non-public gold never reaches GitHub.
- New `scripts/link_lora_adapters.py` (was referenced but missing) — links LoRA
  adapters from a sibling workspace on a fresh clone; no-op if already real.

### Added — self-documenting SQLite deliverables
- `write_annotated_sqlite` / `write_sqlite` (reaction pipeline) and
  `modelmap.write_sqlite` now auto-emit a schema **`README.md`** beside the DB:
  file inventory, headline counts, full introspected table/view schema, the
  `MSRXN:` join gotcha, and copy-paste SQL. Generated from the live DB so it
  cannot drift from the data. Best-effort — never fails a build.
- New CLI `ontomap describe <db.sqlite>` regenerates the schema doc for any
  existing ontomap SQLite on demand.

### Added — asset health doctor
- `ontomap info` now runs a **shape-aware** asset check (not just "path
  exists"): the embedding cache has the six runtime keys + row-alignment, the
  SSO/KO dictionaries parse and are non-empty, and the LoRA adapter dirs are
  real and non-empty. This is the early-warning that would have caught the
  deletion behind this release.

### Tests
- `tests/test_embeddings_cache_format.py` — locks the loader↔regen key contract
  and validates the bundled cache.
- `tests/test_sqlite_readme.py` — every SQLite writer emits a README documenting
  all tables + the MSRXN gotcha; `describe` regenerates on demand.

## [1.5.2] — 2026-06-17

### Fixed — model mapping now returns top-100 per query (was top-10)
- **`map_model` and `map_model_to_sqlite` defaulted to `top_k=10`** but the
  model→ModelSEED deliverable is specified as **top-100 candidates per query**.
  Both defaults are now **`top_k=100`**, and the `ontomap map-model` CLI
  `--top-k` default is bumped to match (`10 → 100`).
- **Retrieval depth now scales with `top_k`** so 100 is genuinely returnable,
  not silently truncated by the candidate pool: `CompoundMapper.map_many`
  retrieves `max(n_retrieve, top_k*4)` synonym vectors (dedup to unique cpd ids)
  and `ReactionMapper.map_many` retrieves `max(n_name, top_k*3)` name vectors
  before the (name ∪ compound-set) union. Behavior is unchanged for `top_k ≤ 50`
  (the prior pool already covered small k); only deep-ranking paths retrieve more.
- The annotation→reaction pipeline (capability 2, `ontomap map` / `Pipeline`)
  is unaffected — its `--top-k` default stays `10`.
- The benchmarked, gold-scored ADP1 deliverable (research workspace step 49) is
  regenerated at top-100 (compound/reaction `predictions` tables now hold up to
  100 ranks per query; the flat JSONL export is renamed `…_top100.jsonl`).

## [1.5.1] — 2026-06-16

### Added — rich SQLite export for model mappings
- **`map_model_to_sqlite(model_json, modelseed_dir=None, path=...)`** and the
  lower-level **`write_sqlite(path, payload)`** (exported as
  `map_model_to_sqlite` / `write_model_sqlite`) — serialize a whole-model
  compound + reaction mapping to a **self-contained** SQLite DB: 8 tables
  (`compound_queries`/`compound_predictions`/`compound_targets`,
  `reaction_queries`/`reaction_predictions`/`reaction_targets`, `performance`,
  `run_metadata`) + 2 join views (`compound_top_n`, `reaction_top_n`).
  ModelSEED target metadata (formula/charge/InChIKey; EC/pathway/status) is
  denormalized so the DB needs no external files to consume.
- **Robust ModelSEED-data resolution**: `modelseed_dir` is now optional on
  `load_compounds`/`load_reactions`/`from_modelseed`/`map_model`/
  `map_model_to_sqlite` — resolves explicit arg → `$ONTOMAP_MODELSEED` →
  bundled `data/modelseed/` (file-relative fallback). `SETUP_ASSETS.md`
  documents fetching `compounds.tsv` + `reactions.tsv`.
- A benchmarked, gold-scored DB for the published ADP1 model ships in the
  research workspace (step 49) with a README reporting RAM/query, queries/sec,
  and total runtime — ready to hand to a downstream pipeline.

### Tooling & onboarding
- **CLI `ontomap map-model`** — run model mapping end-to-end without writing
  Python: `ontomap map-model --model M.json --output mapping.sqlite` (or
  `--format json`).
- **`CLAUDE.md`** at the repo root — a setup-and-run runbook so a new user can
  clone the repo and let Claude Code bootstrap + run it.
- **`scripts/setup.sh`** rewritten to fetch the public assets for model mapping
  (SapBERT + ModelSEED tables) and verify, with the reaction-pipeline assets as
  a clearly-flagged optional step.
- **README** rewritten around the two capabilities; **INSTALL.md** /
  **SETUP_ASSETS.md** updated for a fresh-clone, model-mapping-first flow.
- Version unified at **1.5.1** across `pyproject.toml` + `__init__`.

## [1.5.0] — 2026-06-16

### Added — compound & reaction mapping for whole metabolic models (`ontomap.modelmap`)
A second capability, **additive** to the existing annotation→reaction
`Pipeline`: map the metabolites and reactions of an existing
foreign-namespace metabolic model onto ModelSEED compound **and** reaction
ids. Motivated by Christopher Henry's request to integrate published
models (e.g. an *A. baylyi*/ADP1 reconstruction) whose namespaces don't
match ModelSEED.

- **`CompoundMapper`** — SapBERT multi-synonym embedding + exact
  normalized-synonym index + reaction-network consistency rerank.
- **`ReactionMapper`** — SapBERT reaction-name embedding ∪ stoichiometric
  compound-set overlap (over the ACTIVE corpus, with a canonicality prior).
- **`map_model(model_json, modelseed_dir)`** — one-call whole-model
  mapping (compounds first, reactions reuse them).
- New public exports: `CompoundMapper`, `ReactionMapper`, `map_model`.
- New docs: `docs/COMPOUND_REACTION_MAPPING.md` (results, data
  limitations, I/O, figures); example `examples/06_map_published_model.py`.

### Validation (held-out gold on published ADP1 model, names + network only)
- Compounds: **hit@1 0.934, hit@10 0.996** (n=694); the network rerank is
  a +5.6 pp hit@1 lift; redundancy-aware hit@1 0.944.
- Reactions: **hit@1 0.818, hit@10 0.965** (n=850); restricting the target
  to ACTIVE reactions is decisive (else strict hit@1 collapses to 0.52
  on obsolete duplicates); compound→reaction cascade cost only ~4.6 pp.

### Diagnostic — ModelSEED internal redundancy
- Compounds: 1,691 InChIKey-skeleton duplicate clusters (2,611 redundant
  ids, 10.8%); reactions: 335 exact-stoichiometry duplicate clusters
  (1.09%). Reusable de-duplication maps emitted.

### Notes
- The MedCPT cross-encoder is intentionally **not** used by `modelmap` —
  as a name-only reranker it degrades both tasks (it remains in the
  reaction annotation `Pipeline` where it is validated).

## [1.4.1] — 2026-06-12

### Documentation (no code changes)
- **New `EVALUATION.md`** — full metric taxonomy. Defines:
  - TRUE GOLD vs SILVER vs OTHER-ANNOTATOR AGREEMENT vs NOVEL
  - When `hit@K` is real accuracy vs when it's just agreement with another
    annotator that may itself be wrong
  - When to use `confidence_band` / `top1_margin` / `fused_score`
    (answer: always for inputs with no gold — which is the common case)
  - A suggested reporting template so quoted numbers always carry their
    test-set type label
- **README.md** rewritten with the input-shape examples up top, then a
  "what the output means" section pointing at EVALUATION.md, then
  separate benchmark tables for TRUE GOLD vs SILVER agreement.
- **DATA.md** prefaced with a pointer to EVALUATION.md and a one-paragraph
  summary distinguishing training data from evaluation data.
- **Parent workspace `MASTER_SUMMARY.md`** rewritten with explicit
  gold/silver/agreement/novel framing, separating the 31-gene true-gold
  results (100% hit@10) from the 600-gene silver-agreement results (92%
  hit@10) from the 8 588-input production-readiness signals (coverage,
  confidence band distribution, latency).
- **Step 39 `conclusions.md`** rewritten similarly.

### Why the patch
Earlier docs quoted `hit@K` numbers without distinguishing the kind of
test set, which made the 8 588-input numbers look like accuracy when
they're actually a mix of true-gold accuracy + silver agreement +
tool-vs-tool similarity. This patch makes every quoted number carry
its test-set type label.

## [1.4.0] — 2026-06-12

### Added
- **`Pipeline.map(name=, ec=, notes=, tags=, id=, top_k=)`** — explicit
  structured input for a single query. Compose any combination of name +
  EC + tags + notes without hand-building the text format. Requires at
  least one of `name` / `ec` / `notes` / `tags`. Examples:
  ```python
  pipe.map(name="Aldehyde dehydrogenase", ec="1.2.1.3")
  pipe.map(name="Aldehyde dehydrogenase")     # name only
  pipe.map(ec="1.2.1.3")                       # EC only
  pipe.map(name="Aldehyde dehydrogenase", ec="1.2.1.3",
           tags=["putative", "partial"])
  ```
- **`ontomap map --name "..." --ec "..." [--tags "putative;partial"]`** —
  matching CLI flags for the same shapes. Composes into the same text
  format `Pipeline.map_descriptions` expects.
- **`tests/test_pipeline_map_api.py`** — 19 tests (12 weight-free composition
  + 7 weight-gated integration). All pass.

### Changed
- **Bundle slim-down**: `data/embeddings/sso_source_sapbert.npz` and
  `data/embeddings/ko_source_sapbert.npz` are no longer included or required.
  They were only used by the workspace's `step17_evaluate.evaluate_split`
  research helper (LoRA-vs-base benchmarking), NEVER loaded by the runtime.
  At inference time, source axes (your free-text descriptions or SSO/KO ids)
  are always encoded on-the-fly via the LoRA model, which is the correct
  behaviour for arbitrary user inputs.
- `scripts/regen_embeddings.py` now skips building source caches by default.
  Add `--include-source-caches` to opt in (only needed for split-eval research).
- `_paths.py` no longer treats source NPZs as required artefacts.

### Verified
- All input shapes round-trip cleanly through the CLI and Python API:
  - `name + EC`           → "Aldehyde dehydrogenase (EC 1.2.1.3)" — source_ec='1.2.1.3'
  - `name only`           → "Aldehyde dehydrogenase"               — source_ec=None
  - `EC only`             → "EC 1.2.1.3"                           — source_ec='1.2.1.3'
  - `name + EC + tags`    → "<name> (EC <ec>) [tag1; tag2]"        — source_ec='1.2.1.3'
  - `EC w/ prefix`        → "EC 1.2.1.3" (no double-prefix)        — source_ec='1.2.1.3'
  - `multi-EC`            → "<name> (EC X.Y.Z) (EC A.B.C)"          — source_ec='X;A'

### Migration
- No breaking changes. Existing callers see the same `MapResult` shape.
- New `.map()` method is purely additive — `map_one`, `map_batch`,
  `map_descriptions` unchanged.
- The two removed `.npz` files are reproducible via
  `python scripts/regen_embeddings.py --include-source-caches`.

## [1.3.0] — 2026-06-12

### Added
- **`reaction_meta[rxn_id]["ec_match_level"]`** in `MapResult` — per-prediction
  integer signal of how the query EC relates to the candidate EC: `0` (no
  match), `1` (prefix match — e.g. query `1.10.3` matches candidate
  `1.10.3.10`), `2` (exact match).
- **`reaction_meta[top1_rxn]["confidence_band"]`** — coarse `"high" / "medium"
  / "low"` label for the top-1 prediction derived jointly from the fused
  score and the margin vs the runner-up. Helps callers triage downstream
  review effort without re-implementing the same heuristic.
- **`reaction_meta[top1_rxn]["top1_margin"]`** — numeric `fused_score(rank=1) -
  fused_score(rank=2)`, the same signal as `confidence_band` but raw.
- **`scripts/download_models.py`** — fetches SapBERT + MedCPT and symlinks
  into `weights/`. Idempotent.
- **`scripts/build_corpus.py`** — fetches ModelSEED `reactions.tsv` +
  `compounds.tsv` from upstream; `--patches` also applies the bundled
  78-row EC backfill in-place.
- **`scripts/regen_embeddings.py`** — rebuilds the SapBERT NAME/EC/EQ/PATHWAY
  NPZs under `data/embeddings/`. ~30 s on H100, ~10 min on CPU.
- **`scripts/finetune_lora.py`** — fine-tune a fresh SapBERT-LoRA adapter on
  user `(source_label, target_reaction_id)` TSV pairs. Wraps `peft.LoraConfig`
  + `sentence_transformers.losses.MultipleNegativesRankingLoss` with the
  exact v1.0.0 hyperparameters (r=16, alpha=32, lr=2e-5, batch 128, 3
  epochs, bf16). `--evaluate` computes hit@K + MRR on the held-out split.
- **`scripts/setup.sh`** — one-shot bootstrap: download_models → build_corpus
  --patches → regen_embeddings → smoke test. ~2 min on H100.
- **`examples/01_text_input.py`** through **`examples/05_sqlite_output.py`** —
  5 runnable scripts covering text input, --ec-augment diff, batch CSV +
  SSSOM-TSV output, varied input shapes, SQLite output. `examples/README.md`
  indexes them.
- **`tests/test_ec_priority_unit.py`** — 17 unit tests on the EC helpers
  (`_extract_query_ecs`, `_ec_match_bonus`, `_ec_augmented_candidates`)
  that need no model weights. All pass in CI.
- **`tests/test_input_robustness.py`** — 7 weight-gated cases (empty / >1400
  chars / non-ASCII / dash-EC / multi-EC / name-only / EC-only) using a
  module-scoped pipe fixture; skipped when weights aren't downloaded.
- **`.github/workflows/ci.yml`** — GitHub Actions: ruff lint + import smoke
  + unit tests on every push and PR.
- **`CONTRIBUTING.md`** — what we welcome (bug fixes with tests, corpus EC
  patches, examples) vs decline (reranker swaps without numbers, LLM in
  core path).
- **`DATA.md`** — what training data was used (KBase SSO 2 124 IDs / 3 717
  pairs, KEGG KO 95.0 4 754 IDs / 11 016 pairs, ModelSEED biochemistry
  43 775 reactions); licenses (SSO + ModelSEED CC0, KEGG academic-use,
  MedCPT NIH research-use); how positives were paired + hard negatives
  mined; per-split sizes for Split-A/B/C.
- **`FINETUNE.md`** — step-by-step recipe for retraining the LoRA adapter on
  user data (TSV format, hyperparameters, command, evaluation, swap-in
  procedure).

### Changed
- Public README now leads with version banner + benchmark headline + links
  to the Research-OS provenance trail in the parent workspace.

### Migration
- Existing callers see no breaking changes; `reaction_meta` now has extra
  keys (`ec_match_level`, and on top-1 `confidence_band` + `top1_margin`)
  but unchanged old keys (`name`, `ec_numbers`, `equation`, `pathway`,
  `alt_names`). Old downstream code keeps working; new code can opt in.

## [1.2.0] — 2026-06-12

### Added
- **`--ec-augment` CLI flag** and `Pipeline(ec_augment=True)` constructor
  arg (also `OMAP_EC_AUGMENT=1` env var). When enabled, after the
  SapBERT-LoRA top-100 FAISS retrieval, the runtime scans the bundled
  ModelSEED reactions for any whose `ec_numbers` substring-matches any EC
  extracted from the query description and **merges them into the candidate
  pool** before MedCPT rescore + σ-fusion. Each augmented candidate gets the
  fixed EC-priority bonus added on top, so it competes fairly even with
  `lora_norm = 0`.
- Helper: `_ec_augmented_candidates(query_ecs, rxn_meta, already, max_extra)`
  in `_frozen_runtime.py`.
- New `PipelineConfig.ec_augment: bool = False` (off by default for
  backwards compatibility; recommended ON for unfamiliar enzyme classes).

### Validated
On the 600-gene multi-gold harness (3 RAST sources × 200), enabling
`--ec-augment` is a **no-op** at K=1/5/10/20 because the gold reactions
for our test queries are already in the SapBERT top-100. The lift shows up
on **edge cases** (cytochrome oxidase subunits, multi-EC enzymes) where the
SapBERT NAME axis under-ranks the gold but the EC axis would surface it.
The mechanism is correct; the eval-set distribution doesn't exercise it.

### Investigated but not shipped (mixed results)
- **Lite stacking ensemble** (`(lora_norm, medcpt_norm, ec_match, has_query_ec)` → logreg
  on the 600-gene multi-gold harness): trades K-positions. Lifts hit@5 by +2.2 pp and
  hit@10 by +0.3 pp, but **hurts** hit@1 by -3.5 pp and hit@20 by -1.3 pp. Production
  σ=0.30 fusion remains the better all-K choice. Trained coefficients (lora≈3.95,
  medcpt≈3.78, ec_match≈2.21, has_query_ec≈-1.13) saved to
  `workspace/42_42_corpus_reencode_stacking/data/output/lite_stacking_model_spec.json`
  for users who want to opt in to K=5 maximisation.

### Investigated and rejected (v2 campaign)
After 5 additional Research-OS steps (36–40, plus 42):
- 5 biomedical cross-encoder rerankers (NeuML/biomedbert, PubMedBERT-MIRIAD,
  OverSamu/NCBI-disease, PubMedBERT-MNLI, SciBERT-cross-encoder): all
  **lose** to MedCPT by 11–21 pp hit@10. MedCPT-on-PubMed-search is
  genuinely the best signal for this task.
- 6 meta-reranker ensembles (RRF 2/3-way, weighted-linear grid, Borda,
  stacking-logreg-LOSO): **M6 stacking** is the only one beating baseline
  at hit@5 (+6.2 pp). Not shipped — needs runtime biomed-encoder load
  (~3 s startup + 110 MB RAM).
- Top-200 retrieval (vs top-100): **no lift** — recall@200 = recall@100
  on the multi-gold harness. Ceiling is structural.
- Corpus EC patches retrieval lift: 78 patches reach only 2/434 gold
  reactions in this eval set, so measured lift = 0. Patches are still
  **correct** and ship for future use.

### Documented limits
- Full 8 588-input Acidovorax 3H11 scale test (step 39): mean **39 ms/query**
  (p95 58 ms, 25.3 qps), mean top-1 fused_score **0.940**. On Morgan-Price
  gold (n=31): **hit@10 = 100%**. On RAST silvers (n≈743/source):
  hit@10 ≈ 92%.

## [1.1.0] — 2026-06-12

### Added
- **EC-priority bonus** (default ON): after the σ-fused MedCPT+LoRA score is
  computed, candidates whose `ec_numbers` field contains a substring match of
  any EC extracted from the query description receive a fixed bonus of
  `EC_PRIORITY_BONUS = 0.15` before the final argsort. On the multi-gold harness
  (n=600 across 3 RAST sources) this lifts macro `hit@1` by ~+0.3 pp and
  `frac_recovered@20` by ~+0.7 pp at ~3 ms/query overhead. Disable via
  environment variable `OMAP_DISABLE_EC_PRIORITY=1`.
- **ModelSEED corpus EC patches** (`data/modelseed_corpus_patches.csv`): 78
  reactions whose upstream `ec_numbers` field is empty get auto-detected
  (from name + aliases) or hand-curated EC tags applied at corpus load.
  Includes critical cytochrome oxidase fixes for `rxn14421` (1.10.3.10) and
  `rxn14422` (1.10.3.14) — these were identified in step 33c of the workspace
  campaign as the cause of 3 of 8 top-20 misses on the 95-RAST clean test.
- **Helper functions** in `_frozen_runtime.py`:
  - `_extract_query_ecs(text)` — regex-based EC extraction
  - `_ec_match_bonus(query_ecs, cand_ec_str, bonus)` — EC matching
  - `_load_ec_patches()` — patch loader (cached)

### Investigated and rejected (kept current behaviour)
After a structured 11-experiment campaign (workspace steps 31–40):
- Cross-encoder reranker replacements — every alternative tested (BGE-v2-m3,
  MS-MARCO MiniLM, mxbai-rerank, MedCPT-rich-text, NeuML-biomedbert,
  PubMedBERT-MIRIAD, OverSamu-NCBI-disease, SciBERT-cross-encoder) **lost**
  to the current MedCPT fusion at hit@20 by 1–22 pp. MedCPT-on-PubMed is
  genuinely the strongest signal for this task.
- σ retuning — sigma sweep shows the hit@20 plateau is `σ ∈ [0.2, 0.4]`; the
  shipped `σ_SSO = 0.3` is already on the plateau.
- Listwise LLM rerank — incompatible with the latency budget (and prior
  step-21 work showed marginal gain anyway).
- Query paraphrase fan-out, alias-augmented retrieval — both tied baseline at
  hit@20 with much higher cost.

### Documented limits
- Empirical top-100 ceiling on the 95-RAST clean test: **94.7%**
  (5/95 genes have NO gold candidate in the SapBERT-LoRA top-100 pool —
  these are entity-resolution misses that require subunit-aware retrieval
  or a corpus expansion, NOT a reranker change).
- On the full 600-gene multi-gold harness, recall@100 = **96.0%**.

## [1.0.0] — 2026-06-08

Initial release. SapBERT-LoRA + multi-axis FAISS top-100 retrieval +
MedCPT cross-encoder σ-fusion (σ_SSO=0.3, σ_KO=0.7).
