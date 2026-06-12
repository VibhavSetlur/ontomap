"""`ontomap bench` — reproducible scaling benchmark, mirrors workspace step 26.

For each tier N in `tiers`, samples N non-gold IDs (seeded), runs the frozen
pipeline_3 on them, and records wall-clock latency, peak RAM, peak VRAM, and
output size. Same logic as workspace/26_pipeline_3_scale_benchmark/scripts/26a
but standalone (no workspace dependency).

NOTE: requires either bundled non-gold pools in `data/` or a path to source
dictionaries via env var `ONTOMAP_DATA_DIR`.
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path

import psutil


def _peak_vram_mib() -> float:
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.max_memory_allocated() / (1024**2)
    except ImportError:
        pass
    return 0.0


def _reset_peak_vram() -> None:
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except ImportError:
        pass


def _load_non_gold_pool(direction: str, data_dir: Path) -> list[str]:
    """Build the non-gold pool from bundled dictionaries.

    The package ships small sample pools under data/; if a user has the full
    dictionaries locally, they can point ONTOMAP_DATA_DIR at them.
    """
    if direction == "sso":
        d_path = data_dir / "SSO_dictionary.json"
        gold_path = data_dir / "SSO_reactions.json"
    else:
        d_path = data_dir / "KO_dictionary.json"
        gold_path = data_dir / "kegg_95_0_ko_seed.tsv"

    if not d_path.exists():
        raise FileNotFoundError(
            f"non-gold pool source missing: {d_path}. "
            "Set ONTOMAP_DATA_DIR to a directory containing SSO_dictionary.json + KO_dictionary.json."
        )

    with d_path.open() as f:
        d = json.load(f)
    all_ids = list(d.get("term_hash", d).keys())

    if direction == "sso":
        if gold_path.exists():
            with gold_path.open() as f:
                gold_ids = set(json.load(f).keys())
        else:
            gold_ids = set()
    else:
        gold_ids = set()
        if gold_path.exists():
            with gold_path.open() as f:
                for line in f:
                    if line.startswith("ko_id\t"):
                        continue
                    parts = line.rstrip("\n").split("\t")
                    if parts:
                        gold_ids.add(parts[0])

    return [x for x in all_ids if x not in gold_ids]


def run_bench(
    direction: str = "both",
    tiers: list[int] | None = None,
    device: str = "auto",
    output_dir: Path | None = None,
    seed: int = 17,
) -> dict:
    """Run the scaling benchmark. Returns a JSON-able summary dict."""
    from ontomap.pipeline import Pipeline

    tiers = tiers or [10, 100, 1000]
    directions = ["sso", "ko"] if direction == "both" else [direction]

    data_dir = Path(os.environ.get("ONTOMAP_DATA_DIR", "")) if os.environ.get("ONTOMAP_DATA_DIR") else \
               Path(__file__).resolve().parent.parent / "data"

    rng = random.Random(seed)
    results: list[dict] = []

    for dir_name in directions:
        pool = _load_non_gold_pool(dir_name, data_dir)
        pool_size = len(pool)

        # Cumulative samples: larger N strictly contains smaller N (warm-cache validity).
        max_n = min(max(tiers), pool_size)
        sampled = rng.sample(pool, max_n)

        pipe = Pipeline.from_pretrained(direction=dir_name, device=device)

        for n in tiers:
            if n > pool_size:
                continue
            ids_n = sampled[:n]
            _reset_peak_vram()
            proc = psutil.Process()
            rss_before = proc.memory_info().rss / (1024**2)

            t0 = time.perf_counter()
            r = pipe.map_batch(ids_n, top_k=10, verbose=False)
            wall = time.perf_counter() - t0

            latencies = sorted([x.latency_ms for x in r])
            p50 = latencies[len(latencies) // 2] if latencies else 0.0
            p95 = latencies[int(0.95 * len(latencies))] if latencies else 0.0
            p99 = latencies[int(0.99 * len(latencies))] if latencies else 0.0

            rss_after = proc.memory_info().rss / (1024**2)
            results.append({
                "direction": dir_name,
                "N": n,
                "wall_clock_s": round(wall, 3),
                "queries_per_sec": round(n / max(wall, 1e-9), 3),
                "p50_ms": round(p50, 3),
                "p95_ms": round(p95, 3),
                "p99_ms": round(p99, 3),
                "peak_ram_mib": round(rss_after, 2),
                "ram_delta_mib": round(rss_after - rss_before, 2),
                "peak_vram_mib": round(_peak_vram_mib(), 2),
                "pool_size": pool_size,
            })

    out = {
        "tiers": tiers,
        "directions": directions,
        "seed": seed,
        "results": results,
    }

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "bench_results.json").write_text(json.dumps(out, indent=2))

    return out
