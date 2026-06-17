"""Example 06 — map a whole published model's compounds + reactions to ModelSEED.

NEW in ontomap 1.5.0 (ontomap.modelmap). Maps every metabolite and
reaction of a foreign-namespace COBRA-style model onto ModelSEED ids and
writes a per-entity TSV with the top-1 call + confidence signals.

Usage:
    python 06_map_published_model.py MODEL.json MODELSEED_DIR [OUT_DIR]

  MODEL.json    COBRA-style model: {"metabolites":[{id,name,...}],
                "reactions":[{id,name,metabolites:{met:coef}}]}
  MODELSEED_DIR directory holding compounds.tsv + reactions.tsv
  OUT_DIR       where to write compound_map.tsv / reaction_map.tsv (default .)
"""
import csv
import json
import sys
from pathlib import Path

from ontomap import map_model


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    model_path, modelseed_dir = sys.argv[1], sys.argv[2]
    out_dir = Path(sys.argv[3] if len(sys.argv) > 3 else ".")
    out_dir.mkdir(parents=True, exist_ok=True)

    model = json.loads(Path(model_path).read_text())
    print(f"mapping {len(model['metabolites'])} metabolites + "
          f"{len(model['reactions'])} reactions to ModelSEED ...")
    out = map_model(model, modelseed_dir=modelseed_dir)   # top_k=100 candidates per query (default)

    with (out_dir / "compound_map.tsv").open("w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["local_id", "modelseed_cpd", "score", "exact", "network"])
        for lid, ranked in out["compounds"].items():
            if ranked:
                cid, score, sig = ranked[0]
                w.writerow([lid, cid, round(score, 4),
                            sig.get("exact", 0), round(sig.get("net", 0.0), 3)])

    with (out_dir / "reaction_map.tsv").open("w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["local_id", "modelseed_rxn", "score", "name_sim", "set_jaccard", "exact_set"])
        for lid, ranked in out["reactions"].items():
            if ranked:
                rid, score, sig = ranked[0]
                w.writerow([lid, rid, round(score, 4), round(sig.get("name", 0.0), 3),
                            round(sig.get("set_jac", 0.0), 3), int(sig.get("exact_set", 0))])

    print(f"wrote {out_dir/'compound_map.tsv'} and {out_dir/'reaction_map.tsv'}")


if __name__ == "__main__":
    main()
