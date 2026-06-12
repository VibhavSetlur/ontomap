# ontomap — validation

All numbers below are from the **frozen pipeline_3** (`weights/lora/{sso,ko}` + `weights/medcpt` + `weights/swept_weights.json`) on the held-out **Split-C EC-3-disjoint** test fold. No LLM. SSO n=235, KO n=456.

## Gold-set accuracy

| metric | SSO | KO |
|---|---:|---:|
| hits@1 | 0.5149 | 0.4825 |
| hits@5 | 0.7915 | 0.7412 |
| **hits@10** | **0.8128** | **0.7895** |
| hits@20 | 0.8128 | 0.7895 |
| MRR | 0.6393 | 0.5947 |
| Bpref | 0.5093 | 0.4842 |
| **EC-soft@10** | **0.8936** | **0.8969** |

Bootstrap 95 % CIs on Δhits@10 vs the no-LoRA baseline:
- SSO: **+9.36 pp** [+5.11, +13.19], p<0.001
- KO:  **+6.14 pp** [+3.73, +8.77],  p<0.001

## Component ablation (Δhits@10 marginal)

| stage added | SSO | KO |
|---|---:|---:|
| Baseline SapBERT (Stage 0) | 0.7191 | 0.7281 |
| + LoRA NAME+EC (Stage 1) | **+8.51 pp** | **+5.92 pp** |
| + MedCPT fused rerank (Stage 2 = pipeline_3) | **+9.36 pp** | **+6.14 pp** |

LoRA is the load-bearing component; MedCPT-fused adds a top-of-list refinement.

## Cost of removing the Qwen2.5-7B listwise reranker

Paired-bootstrap comparison vs the with-LLM ensemble (same Split-C sources):

| metric | SSO Δ (no-LLM − LLM) | KO Δ (no-LLM − LLM) |
|---|---:|---:|
| hits@1 | **+2.55 pp** (no-LLM better) | −3.73 pp |
| hits@5 | +1.70 pp | −0.44 pp |
| hits@10 | 0.00 | 0.00 (identical) |
| hits@20 | 0.00 | 0.00 |
| MRR | +2.47 pp | −2.35 pp |
| Bpref | +5.62 pp | −0.38 pp |
| EC-soft@10 | 0.00 | 0.00 |

The LLM only re-orders within top-10, so set membership at top-10 is mathematically unchanged. The only metric where the LLM contributed real lift was **KO hits@1** (−3.73 pp without it). Removing it saves ~770 ms/query and ~30 GB VRAM.

## Biological-validity diagnostics

- **EC-soft@10 ≈ 0.89** both directions — top-10 contains a reaction sharing ≥3 EC levels with the curated gold in ~89 % of queries.
- **49.5 % of SSO queries** get a perfect EC-3 family return list (all 10 top candidates share the gold's EC-3 class).
- **70 % SSO / 80 % KO** of strict-misses are biochemically plausible siblings per blind LLM-as-judge audit (project step 09).
- **41.5 % cross-direction top-1 agreement** between SSO and KO pipelines on shared gold reactions; 68 % transitive. The 22 % "agree-but-wrong" band identifies substrate-class confusion within the right EC family.

## Provenance + reproduction

- **Frozen artefacts**: `weights/lora/{sso,ko}-splitC` (~11 MB each), `weights/medcpt/` (440 MB), `weights/swept_weights.json` (frozen step 01 coord-descent weights), `data/embeddings/*.npz` (cached SapBERT corpus + source embeddings).
- **Reproduce these numbers**: `pytest -m slow` (requires GPU; runs the actual pipeline_3 on bundled Split-C splits).
- **Or rerun the upstream pipeline**: workspace step `25_pipeline_3_frozen_gold_eval` in the project repo.
- **Audit trail**: `synthesis/AUDIT.md` in the upstream project — dashboard-claim verification, citation cross-check, methodology vs literature, plus the cost-of-removing-LLM table above.

## Open caveats

- **n_test is small** (235 / 456 on Split-C). Bootstrap CIs reflect this honestly; ±3–4 pp bands are not statistical fragility, they are appropriate uncertainty.
- **MedCPT-fused σ weights** (σ_SSO=0.3, σ_KO=0.7) are frozen from step-18 variant-C and not re-swept on Split-C; small Δ possible if re-swept.
- **CPU latency** estimated 10× GPU per project step 22 helper timings; the bundled `ontomap bench` measures real CPU numbers on your hardware.
- **Calibrated confidence** is currently the raw fused score; the isotonic-regression calibrator is bundled but not wired into the runtime yet (Phase 8.1).
