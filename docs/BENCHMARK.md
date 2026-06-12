# ontomap — benchmark + scaling

Frozen pipeline_3 (no LLM) run on non-gold source pools at four scale tiers per direction (cumulative sample, seed 17). Hardware: 1× NVIDIA H100 NVL. Pool sizes: SSO non-gold = 42 230, KO non-gold = 17 848.

## Scaling table

| direction | N | wall (s) | **avg ms / query (warm)** | **queries / sec** | p95 ms | peak VRAM | peak RAM | output |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SSO | 10 | 43.4 | 221 | 0.23 | 275 | 6 288 MiB | 2 440 MiB | 0.01 MB |
| SSO | 100 | 56.1 | 169 | 1.78 | 209 | 6 288 MiB | 2 599 MiB | 0.10 MB |
| SSO | 1 000 | 221.0 | 137 | 4.52 | 194 | 6 288 MiB | 2 955 MiB | 0.97 MB |
| **SSO** | **5 000** | **564.1** | **107** | **8.86** | 144 | 6 288 MiB | 3 263 MiB | 4.86 MB |
| KO | 10 | 28.6 | 95 | 0.35 | 115 | 6 288 MiB | 3 347 MiB | 0.01 MB |
| KO | 100 | 37.9 | 102 | 2.64 | 127 | 6 288 MiB | 3 365 MiB | 0.10 MB |
| KO | 1 000 | 127.7 | 100 | 7.83 | 133 | 6 288 MiB | 3 341 MiB | 0.96 MB |
| **KO** | **5 000** | **537.6** | **102** | **9.30** | 137 | 6 288 MiB | 3 465 MiB | 4.81 MB |

**Key facts:**
1. **Peak VRAM is N-independent at 6.3 GB.** Fits any modern GPU (RTX 3060+, A4000+, T4 cloud); single-host one-process serves every tier.
2. **Average per-query latency converges** to ~100 ms (KO) and ~100–130 ms (SSO) by N=1 000 — per-query cost *decreases* with N because LoRA-load + cuBLAS warm-up are amortised.
3. **Throughput saturates near 9 queries/sec** per direction on one H100. Two processes on two GPUs ≈ 2×. The bottleneck is the MedCPT-cross-encoder forward over 100 candidates; a 4× MedCPT-batching speedup is a known optimisation not currently shipped.
4. **Host RAM scales sub-linearly.** SSO RSS grows from 2.4 GB (N=10) to 3.3 GB (N=5 000) — about +180 MiB per 1 000 queries.

## Storage footprint

| artefact | size |
|---|---:|
| SapBERT base | 438 MB |
| MedCPT cross-encoder | 438 MB |
| LoRA adapters (SSO + KO) | 22 MB |
| SapBERT cached corpus embeddings | 367 MB |
| SapBERT cached source embeddings (SSO + KO) | 37 MB |
| ModelSEED corpus + compounds + aliases | 50 MB |
| Source dictionaries (SSO + KO) | 9 MB |
| Curated gold mappings (for repro) | < 1 MB |
| Splits + meta (Split-A/B/C labels) | 3 MB |
| **Total bundled (dereferenced for share)** | **~1.4 GB** |

## Run the benchmark on your hardware

```bash
ontomap bench --tiers 10,100,1000 --direction both
# Full reproduction of the table above (takes ~30 min):
ontomap bench --tiers 10,100,1000,5000 --direction both --output-dir /tmp/bench
```

The benchmark uses the same `_frozen_runtime` as `ontomap map`. It samples the non-gold pool deterministically (seed 17) so two runs on the same hardware should agree on wall-clock to within ±5 %.

## Confidence distributions on non-gold

The `data/output/*.jsonl` produced by the project step 26 includes the fused σ-weighted top-1 score per non-gold query. KDEs of the distribution show both directions are bimodal: a high-density mode near ~0.95–1.0 (LoRA and MedCPT agreeing confidently) and a broad shoulder at 0.7–0.9 (the disagreement zone). The shoulder is wider for KO than SSO, consistent with KO's lower gold-set hits@1.

**Production-deployment hint:** an abstention threshold around fused-score 0.85 would route ~50–60 % of queries to "high-confidence auto-accept" and leave the rest for human review.

## Comparison with the project's headline numbers

The headline gold-set numbers (`docs/VALIDATION.md`) and these scaling numbers describe the same frozen pipeline_3. The gold-set numbers measure *accuracy*; this benchmark measures *operational characteristics*. Together they form the complete evidence base a downstream user needs to decide "should I integrate ontomap into my workflow?".

## Limitations

- Single-host, single-direction-per-process measurement. Real production deployments will parallelise.
- The N=10 timing is dominated by one-shot setup (~30 s LoRA-load + ~7 s MedCPT-load + cuBLAS warm-up); per-query asymptotes from N=100 onward.
- Cumulative-tier design carries warm state across tiers in a single Python run. For per-tier cold-cache timing, invoke the runner from a fresh process per tier.
