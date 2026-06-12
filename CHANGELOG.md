# Changelog

All notable changes to ontomap are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
