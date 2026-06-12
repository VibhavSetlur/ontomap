# Changelog

All notable changes to ontomap are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
