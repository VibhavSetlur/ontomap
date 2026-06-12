"""02 — ec_augment=True vs False diff.

Demonstrates the v1.2.0 EC-augmented retrieval option. Same 3 descriptions
are mapped twice (ec_augment=False, then ec_augment=True). For each query
we print which reaction ids enter / leave the top-10, illustrating the
candidate-pool augmentation.

When `ec_augment=True`, after the SapBERT-LoRA top-100 FAISS retrieval, the
runtime scans the ModelSEED corpus for any reactions whose `ec_numbers`
substring-match any EC extracted from the query description, and merges
them into the candidate pool before MedCPT rescore + sigma-fusion.

Run from anywhere with the ontomap weights bundled in:
    python /scratch/vsetlur/ontology-mapping/ontomap/examples/02_ec_augment.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/scratch/vsetlur/ontology-mapping/ontomap")

from ontomap import Pipeline  # noqa: E402


DESCRIPTIONS = [
    "Enoyl-CoA hydratase (EC 4.2.1.17)",
    "Cytochrome c oxidase subunit I (EC 1.9.3.1)",
    "DNA-directed RNA polymerase subunit alpha (EC 2.7.7.6)",
]
IDS = ["gene_001", "gene_002", "gene_003"]
TOP_K = 10


def _top_rxns(result, k: int) -> list[str]:
    return [rxn_id for rxn_id, _ in result.predictions[:k]]


def _format_row(rank: int, rxn_id: str, score: float, meta: dict) -> str:
    name = (meta.get("name") or "")[:42]
    ec_list = ",".join(meta.get("ec_list") or []) or "-"
    return f"    {rank:<4}  {rxn_id:<12}  {score:.3f}   {ec_list:<14}  {name}"


def main() -> None:
    print("Running ec_augment=False ...")
    pipe_off = Pipeline.from_pretrained(direction="sso", ec_augment=False)
    results_off = pipe_off.map_descriptions(
        DESCRIPTIONS, ids=IDS, top_k=TOP_K, verbose=False
    )

    print("Running ec_augment=True ...")
    pipe_on = Pipeline.from_pretrained(direction="sso", ec_augment=True)
    results_on = pipe_on.map_descriptions(
        DESCRIPTIONS, ids=IDS, top_k=TOP_K, verbose=False
    )

    print(f"\nDiff: top-{TOP_K} candidates per query, ec_augment=False -> True\n")
    for r_off, r_on in zip(results_off, results_on):
        print(f"=== {r_off.query_id} :: {r_off.source_name!r}")
        print(f"    EC extracted: {r_off.source_ec or '(none)'}")
        top_off = _top_rxns(r_off, TOP_K)
        top_on = _top_rxns(r_on, TOP_K)
        added = [x for x in top_on if x not in top_off]
        removed = [x for x in top_off if x not in top_on]
        common = [x for x in top_off if x in top_on]

        print(f"    common: {len(common)} reactions")
        if added:
            print(f"    NEW with ec_augment=True : {added}")
        else:
            print("    NEW with ec_augment=True : (none)")
        if removed:
            print(f"    DROPPED                  : {removed}")
        else:
            print("    DROPPED                  : (none)")

        print(f"\n    ec_augment=False  top-{TOP_K}")
        print(f"    rank  rxn_id        fused   ec_list         name")
        for i, (rxn_id, score) in enumerate(r_off.predictions[:TOP_K], start=1):
            print(_format_row(i, rxn_id, score, r_off.reaction_meta.get(rxn_id, {})))

        print(f"\n    ec_augment=True   top-{TOP_K}")
        print(f"    rank  rxn_id        fused   ec_list         name")
        for i, (rxn_id, score) in enumerate(r_on.predictions[:TOP_K], start=1):
            print(_format_row(i, rxn_id, score, r_on.reaction_meta.get(rxn_id, {})))
        print()


if __name__ == "__main__":
    main()
