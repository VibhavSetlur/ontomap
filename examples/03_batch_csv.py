"""03 — batch CSV -> SSSOM-TSV demo.

Reads `examples/sample_ids.csv`, maps the SSO ids with the frozen pipeline,
and writes top-10 SSSOM-TSV output to stdout. Demonstrates both single-query
`map_one` and bulk `map_batch` calls.

Run:
    python /scratch/vsetlur/ontology-mapping/ontomap/examples/03_batch_csv.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/scratch/vsetlur/ontology-mapping/ontomap")

from ontomap import Pipeline  # noqa: E402
from ontomap.io import read_ids, write_results  # noqa: E402


CSV_PATH = Path("/scratch/vsetlur/ontology-mapping/ontomap/examples/sample_ids.csv")
TOP_K = 10


def main() -> None:
    ids = read_ids(CSV_PATH, id_column="sso_id")
    print(f"# loaded {len(ids)} SSO ids from {CSV_PATH}", file=sys.stderr)
    for sso_id in ids:
        print(f"#   {sso_id}", file=sys.stderr)

    pipe = Pipeline.from_pretrained(direction="sso", device="auto")

    # --- single-query path via map_one ---------------------------------------
    print(f"\n# === map_one demonstration ===", file=sys.stderr)
    first_id = ids[0]
    r = pipe.map_one(first_id, top_k=TOP_K)
    print(
        f"# {first_id} -> {r.top1[0] if r.top1 else '(no top1)'} "
        f"({r.top1[1]:.3f} if r.top1 else '-')  "
        f"latency={r.latency_ms:.1f} ms  cold={r.cold}",
        file=sys.stderr,
    )

    # --- bulk path via map_batch (preferred for >1 query) --------------------
    print(f"\n# === map_batch demonstration ({len(ids)} ids) ===", file=sys.stderr)
    results = pipe.map_batch(ids, top_k=TOP_K, verbose=False)

    # Emit SSSOM-TSV via write_results into a temp file, then stream to stdout
    # so callers can pipe it (e.g. `python 03_batch_csv.py > out.sssom.tsv`).
    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "results.sssom.tsv"
        write_results(results, out_path, direction="sso")
        sys.stdout.write(out_path.read_text())


if __name__ == "__main__":
    main()
