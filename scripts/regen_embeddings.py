#!/usr/bin/env python3
"""Regenerate the bundled SapBERT corpus embedding (the only one the runtime needs).

After cloning + downloading weights (download_models.py) + corpus (build_corpus.py),
run this to compute the pre-encoded NumPy NPZ that the runtime reads at load:

    python scripts/regen_embeddings.py

Outputs (~350 MB, written under data/embeddings/):
  target_sapbert.npz       — NAME / EC / EQUATION / PATHWAY embeddings for all
                             non-obsolete ModelSEED reactions (~43 k rows × 4 axes)

The runtime encodes SOURCE inputs (your free-text descriptions or SSO/KO ids)
fresh on every call with the LoRA model — no pre-cached source embeddings are
needed for production. The `--include-source-caches` flag will additionally
build `{sso,ko}_source_sapbert.npz`, which are only needed by the workspace
`step17_evaluate.evaluate_split` research helper (LoRA-vs-base benchmarking).

Takes ~30 s on 1× H100, ~10 min on CPU.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
EMB_DIR = REPO_ROOT / "data" / "embeddings"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-source-caches", action="store_true",
                    help="ALSO build {sso,ko}_source_sapbert.npz (only needed for "
                         "step17_evaluate.evaluate_split research; NOT used by runtime)")
    args = ap.parse_args()

    EMB_DIR.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(REPO_ROOT))

    from ontomap._helpers.ontomap_lib import data as omdata
    from ontomap._helpers.ontomap_lib.multi_axis import (
        render_source_axes, render_target_axes,
    )
    from sentence_transformers import SentenceTransformer

    print("Loading SapBERT base encoder …")
    sapbert_path = REPO_ROOT / "weights" / "sapbert"
    if not sapbert_path.exists():
        print(f"ERROR: {sapbert_path} not found. Run `python scripts/download_models.py` first.")
        sys.exit(1)
    model = SentenceTransformer(str(sapbert_path))
    print(f"  device: {model.device}")

    # ---------------- ModelSEED target corpus ----------------
    print("\n[target] rendering ModelSEED corpus axes …")
    rxn = omdata.load_modelseed_reactions()
    rxn_ecs = omdata.load_modelseed_reaction_ecs()
    rxn_paths = omdata.load_modelseed_reaction_pathways()
    rxn_names = omdata.load_modelseed_reaction_names()
    ids, name_t, ec_t, eq_t, pw_t = [], [], [], [], []
    for rid, row in rxn.items():
        if row.get("is_obsolete") in ("1", "true", "True"):
            continue
        ax = render_target_axes(row, rxn_ecs.get(rid), rxn_paths.get(rid), rxn_names.get(rid))
        ids.append(rid)
        name_t.append(ax["NAME"])
        ec_t.append(ax["EC"])
        eq_t.append(ax["EQUATION"])
        pw_t.append(ax["PATHWAY"])
    print(f"  {len(ids)} non-obsolete reactions")

    def encode(texts, axis):
        t0 = time.time()
        emb = model.encode(texts, batch_size=128, normalize_embeddings=True,
                           show_progress_bar=False, convert_to_numpy=True).astype("float32")
        print(f"  {axis:8} {emb.shape} in {time.time()-t0:.1f}s")
        return emb

    name_e = encode(name_t, "NAME")
    ec_e   = encode(ec_t,   "EC")
    eq_e   = encode(eq_t,   "EQUATION")
    pw_e   = encode(pw_t,   "PATHWAY")
    out = EMB_DIR / "target_sapbert.npz"
    np.savez_compressed(out, ids=np.array(ids), name=name_e, ec=ec_e, equation=eq_e, pathway=pw_e)
    print(f"  → {out}  ({out.stat().st_size/1e6:.1f} MB)")

    if not args.include_source_caches:
        print("\n[source-caches] skipped (use --include-source-caches to build them; "
              "they're only needed for split-eval research, NOT for the runtime)")
        print("\n✓ Done. Run `ontomap info` or `ontomap map --text 'Enoyl-CoA hydratase (EC 4.2.1.17)'` to verify.")
        return

    # ---------------- SSO / KO source dictionaries ----------------
    for direction, loader in [("sso", omdata.load_sso_dictionary),
                               ("ko",  omdata.load_ko_dictionary)]:
        print(f"\n[source.{direction}] rendering …")
        d = loader()
        src_ids, name_t, ec_t = [], [], []
        for sid, entry in d.items():
            label = entry.get("name") or entry.get("definition") or sid
            ax = render_source_axes(label)
            src_ids.append(sid)
            name_t.append(ax["NAME"] or sid)
            ec_t.append(ax["EC"] or ax["NAME"] or sid)
        print(f"  {len(src_ids)} {direction.upper()} entries")
        name_e = encode(name_t, "NAME")
        ec_e   = encode(ec_t,   "EC")
        out = EMB_DIR / f"{direction}_source_sapbert.npz"
        np.savez_compressed(out, ids=np.array(src_ids), name=name_e, ec=ec_e)
        print(f"  → {out}  ({out.stat().st_size/1e6:.1f} MB)")

    print("\n✓ Done. Run `ontomap info` or `ontomap map --text 'Enoyl-CoA hydratase (EC 4.2.1.17)'` to verify.")


if __name__ == "__main__":
    main()
