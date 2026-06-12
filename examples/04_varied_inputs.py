"""04 — varied free-text input shapes.

The frozen pipeline accepts free-text annotations in many forms. The EC
extractor pulls any `EC X.Y.Z[.W]` substring (or any `\\d+\\.\\d+\\.\\d+\\.\\d+`
pattern) into the EC axis. The remaining text is fed to SapBERT-LoRA.

This example sends 4 progressively richer inputs through the pipeline and
prints `source_name`, `source_ec`, and the top-3 candidates for each so you
can see how each shape is parsed.

Run:
    python /scratch/vsetlur/ontology-mapping/ontomap/examples/04_varied_inputs.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/scratch/vsetlur/ontology-mapping/ontomap")

from ontomap import Pipeline  # noqa: E402


CASES = [
    ("name_only",         "aldehyde dehydrogenase"),
    ("ec_only",           "EC 1.2.1.3"),
    ("name_plus_ec",      "aldehyde dehydrogenase (EC 1.2.1.3)"),
    ("name_ec_and_notes", "aldehyde dehydrogenase (EC 1.2.1.3) [putative; partial]"),
]


def main() -> None:
    pipe = Pipeline.from_pretrained(direction="sso", ec_augment=True)

    descriptions = [text for _, text in CASES]
    ids = [tag for tag, _ in CASES]

    results = pipe.map_descriptions(descriptions, ids=ids, top_k=3, verbose=False)

    for (tag, text), r in zip(CASES, results):
        print(f"=== {tag}")
        print(f"    input        : {text!r}")
        print(f"    source_name  : {r.source_name!r}")
        print(f"    source_ec    : {r.source_ec!r}")
        print(f"    n_predictions: {len(r.predictions)}")
        print(f"    rank  rxn_id        fused   ec_list         name")
        for i, (rxn_id, score) in enumerate(r.predictions[:3], start=1):
            meta = r.reaction_meta.get(rxn_id, {})
            name = (meta.get("name") or "")[:40]
            ec_list = ",".join(meta.get("ec_list") or []) or "-"
            print(f"    {i:<4}  {rxn_id:<12}  {score:.3f}   {ec_list:<14}  {name}")
        print()


if __name__ == "__main__":
    main()
