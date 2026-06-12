"""Programmatic ontomap quickstart — mirrors examples/quickstart.sh but via Python.

Run from anywhere after `pip install -e .` from the ontomap/ folder.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from ontomap import Pipeline
from ontomap.io import write_results


def main() -> None:
    # ── single query ────────────────────────────────────────────────────────
    print("▶ Single-query map · SSO")
    sso = Pipeline.from_pretrained(direction="sso", device="auto")
    r = sso.map_one("SSO:000000027", top_k=5)
    print(f"  top-1: {r.top1}    latency: {r.latency_ms:.1f} ms    cold: {r.cold}")

    # ── batch + multi-format output ────────────────────────────────────────
    ids = [
        "SSO:000000027", "SSO:000000028", "SSO:000000038",
        "SSO:000000079", "SSO:000000147", "SSO:000022185",
    ]
    print(f"\n▶ Batch map · {len(ids)} SSO ids")
    results = sso.map_batch(ids, top_k=100, verbose=False)

    with tempfile.TemporaryDirectory() as td:
        out = Path(td)

        # JSON (rich per-query shape)
        write_results(results, out / "results.json")
        # SSSOM-TSV (bio-ontology standard)
        write_results(results, out / "results.sssom.tsv", direction="sso")
        # SQLite (3-table schema + top_n_with_meta view)
        write_results(results, out / "results.sqlite", direction="sso")
        # Directory mode (one file per query)
        write_results(results, out / "batch_out", output_format="dir")

        # Show SQLite query
        print("\n▶ SQLite — top-3 per query from the view")
        conn = sqlite3.connect(str(out / "results.sqlite"))
        for row in conn.execute("""
            SELECT query_id, rank, reaction_id, ROUND(fused_score, 3), predicate
            FROM top_n_with_meta WHERE rank <= 3
            ORDER BY query_id, rank
        """):
            print(f"  {row}")
        conn.close()

        # Show directory mode layout
        print("\n▶ Directory output layout")
        manifest = json.loads((out / "batch_out" / "manifest.json").read_text())
        print(f"  manifest: {len(manifest['directions'])} direction(s),"
              f" {manifest['n_queries']} queries")
        for sub in (out / "batch_out").rglob("*.json"):
            print(f"  · {sub.relative_to(out / 'batch_out')}")


if __name__ == "__main__":
    main()
