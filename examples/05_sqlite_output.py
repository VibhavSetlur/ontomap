"""05 — SQLite output with the 3-table normalised schema.

Demonstrates `ontomap.io.write_sqlite`, which writes a queryable SQLite DB
with three normalised tables (`queries`, `predictions`, `reactions`) plus a
convenience view `top_n_with_meta` joining them.

After writing the DB this example runs three illustrative SQL queries:
  1. top-3 reactions per query (using the view)
  2. all queries whose top-1 reaction is in pathway X
  3. reverse lookup — which queries mapped to reaction Y

Run:
    python /scratch/vsetlur/ontology-mapping/ontomap/examples/05_sqlite_output.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/scratch/vsetlur/ontology-mapping/ontomap")

from ontomap import Pipeline  # noqa: E402
from ontomap.io import write_sqlite  # noqa: E402


DESCRIPTIONS = [
    "Enoyl-CoA hydratase (EC 4.2.1.17)",
    "Glutamine synthetase (EC 6.3.1.2)",
    "Glucokinase (EC 2.7.1.2)",
    "Phenylacetyl-CoA epoxidase subunit A",
    "ABC transporter substrate-binding protein",
]
IDS = [f"gene_{i:03d}" for i in range(len(DESCRIPTIONS))]


def main() -> None:
    print(f"Loading SSO pipeline ...")
    pipe = Pipeline.from_pretrained(direction="sso", ec_augment=False)

    print(f"Mapping {len(DESCRIPTIONS)} descriptions, top-10 each ...")
    results = pipe.map_descriptions(DESCRIPTIONS, ids=IDS, top_k=10, verbose=False)

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "ontomap_results.sqlite"
        write_sqlite(results, db_path)
        print(f"\nWrote SQLite DB to {db_path} ({db_path.stat().st_size} bytes)")

        conn = sqlite3.connect(str(db_path))
        try:
            # Schema overview
            print("\n=== Schema (tables + view)")
            for row in conn.execute(
                "SELECT type, name FROM sqlite_master "
                "WHERE type IN ('table','view') ORDER BY type, name"
            ):
                print(f"   {row[0]:<5}  {row[1]}")

            # 1. top-3 reactions per query using the convenience view
            print("\n=== Query 1 — top-3 per query via top_n_with_meta")
            print("   query_id     rank  rxn_id        fused   ec_list             reaction_name")
            for row in conn.execute(
                """
                SELECT query_id, rank, reaction_id, ROUND(fused_score, 3),
                       ec_list, reaction_name
                FROM top_n_with_meta
                WHERE rank <= 3
                ORDER BY query_id, rank
                """
            ):
                qid, rank, rxn_id, score, ec_list, name = row
                print(
                    f"   {qid:<11}  {rank:<4}  {rxn_id:<12}  {score:<6}  "
                    f"{(ec_list or '-')[:18]:<18}  {(name or '')[:30]}"
                )

            # 2. cross-table — reactions with EC matching a specific class
            print("\n=== Query 2 — predictions whose reaction has EC starting with '6.3.'")
            for row in conn.execute(
                """
                SELECT q.query_id, p.rank, p.reaction_id, r.ec_list, r.name
                FROM predictions p
                JOIN queries   q ON q.query_id    = p.query_id
                JOIN reactions r ON r.reaction_id = p.reaction_id
                WHERE r.ec_list LIKE '%"6.3.%'
                ORDER BY p.fused_score DESC LIMIT 5
                """
            ):
                print(f"   {row}")

            # 3. reverse lookup — which queries ranked a specific reaction in their top-5?
            print("\n=== Query 3 — counts of distinct queries per reaction (top-5 only)")
            for row in conn.execute(
                """
                SELECT reaction_id, COUNT(DISTINCT query_id) AS n_queries
                FROM predictions
                WHERE rank <= 5
                GROUP BY reaction_id
                ORDER BY n_queries DESC, reaction_id LIMIT 10
                """
            ):
                print(f"   {row[0]:<12}  n_queries={row[1]}")
        finally:
            conn.close()


if __name__ == "__main__":
    main()
