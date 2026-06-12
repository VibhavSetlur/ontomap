"""01 — minimal free-text mapping example.

Map 3 free-text functional annotations to ModelSEED reactions and print the
top-5 per query (rxn_id, reaction name, EC list, fused_score).

Run from anywhere with the ontomap weights bundled in:
    python /scratch/vsetlur/ontology-mapping/ontomap/examples/01_text_input.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/scratch/vsetlur/ontology-mapping/ontomap")

from ontomap import Pipeline  # noqa: E402


DESCRIPTIONS = [
    "Enoyl-CoA hydratase (EC 4.2.1.17)",
    "Glutamine synthetase (EC 6.3.1.2)",
    "ABC transporter substrate-binding protein",
]
IDS = ["gene_001", "gene_002", "gene_003"]


def main() -> None:
    print(f"Loading SSO pipeline (ec_augment=False)...")
    pipe = Pipeline.from_pretrained(direction="sso", ec_augment=False)

    print(f"\nMapping {len(DESCRIPTIONS)} free-text descriptions, top-5 each\n")
    results = pipe.map_descriptions(DESCRIPTIONS, ids=IDS, top_k=5, verbose=False)

    for r in results:
        print(f"=== {r.query_id} :: {r.source_name!r}")
        print(f"    EC extracted from text: {r.source_ec or '(none)'}")
        if not r.predictions:
            print("    (no predictions)")
            continue
        print(f"    rank  rxn_id        fused   ec_list                  name")
        for i, (rxn_id, score) in enumerate(r.predictions[:5], start=1):
            meta = r.reaction_meta.get(rxn_id, {})
            name = (meta.get("name") or "")[:40]
            ec_list = ",".join(meta.get("ec_list") or []) or "-"
            print(f"    {i:<4}  {rxn_id:<12}  {score:.3f}   {ec_list:<22}   {name}")
        print()


if __name__ == "__main__":
    main()
