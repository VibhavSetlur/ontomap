#!/usr/bin/env python3
"""Regenerate the bundled SapBERT corpus embedding (the only one the runtime needs).

After cloning + downloading weights (download_models.py) + corpus (build_corpus.py),
run this to compute the pre-encoded NumPy NPZ that the runtime reads at load:

    python scripts/regen_embeddings.py

Outputs (~350 MB, written under data/embeddings/):
  target_sapbert.npz       — NAME / EC / EQUATION / PATHWAY embeddings for all
                             non-obsolete ModelSEED reactions (~36 k rows × 4 axes).
                             Keys: ids, name_emb, ec_emb, eq_emb, pw_emb, ecs_raw
                             (these MUST match step17_evaluate.load_base_cache).

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

# The exact keys the runtime loader requires (step17_evaluate.load_base_cache).
TARGET_CACHE_KEYS = ("ids", "name_emb", "ec_emb", "eq_emb", "pw_emb", "ecs_raw")


def _verify_target_cache(path: Path, n_expected: int) -> None:
    """Reload the just-written cache and assert the runtime can read it.

    Guards against the v1.5.x regression where this script wrote keys
    (name/ec/equation/pathway) the runtime never reads — shipping a cache
    that loaded fine here but crashed at `ontomap map` time.
    """
    arr = np.load(path)
    missing = [k for k in TARGET_CACHE_KEYS if k not in arr.files]
    if missing:
        raise SystemExit(
            f"FATAL: {path.name} missing runtime keys {missing}; "
            f"got {sorted(arr.files)}. The runtime loader would fail."
        )
    n = len(arr["ids"])
    for k in ("name_emb", "ec_emb", "eq_emb", "pw_emb", "ecs_raw"):
        if len(arr[k]) != n:
            raise SystemExit(
                f"FATAL: {path.name} key '{k}' has {len(arr[k])} rows, "
                f"expected {n} (row-misaligned cache)."
            )
    if n != n_expected:
        raise SystemExit(
            f"FATAL: {path.name} has {n} rows, expected {n_expected}."
        )
    print(f"  [self-check] OK — {n} rows, keys {list(TARGET_CACHE_KEYS)}")


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
    ids, name_t, ec_t, eq_t, pw_t, ecs_raw_t = [], [], [], [], [], []
    for rid, row in rxn.items():
        if row.get("is_obsolete") in ("1", "true", "True"):
            continue
        ax = render_target_axes(row, rxn_ecs.get(rid), rxn_paths.get(rid), rxn_names.get(rid))
        ids.append(rid)
        name_t.append(ax["NAME"])
        ec_t.append(ax["EC"])
        eq_t.append(ax["EQUATION"])
        pw_t.append(ax["PATHWAY"])
        # raw EC list per reaction, ";"-joined — the runtime's EC-hierarchy
        # rerank reads this back via ecs_raw (see step17_evaluate.load_base_cache)
        ecs_raw_t.append(";".join(ax.get("_ecs_raw") or []))
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
    # IMPORTANT: key names MUST match what the runtime loader reads
    # (ontomap/_helpers/step17_evaluate.py::load_base_cache):
    #   ids, name_emb, ec_emb, eq_emb, pw_emb, ecs_raw
    # A mismatch here ships a cache the runtime cannot load (the v1.5.x bug).
    np.savez_compressed(
        out,
        ids=np.array(ids),
        name_emb=name_e, ec_emb=ec_e, eq_emb=eq_e, pw_emb=pw_e,
        ecs_raw=np.array(ecs_raw_t),
    )
    print(f"  → {out}  ({out.stat().st_size/1e6:.1f} MB)")
    _verify_target_cache(out, n_expected=len(ids))

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
        src_ids, name_t, ec_t, ecs_raw_t = [], [], [], []
        for sid, entry in d.items():
            label = entry.get("name") or entry.get("definition") or sid
            ax = render_source_axes(label)
            src_ids.append(sid)
            name_t.append(ax["NAME"] or sid)
            ec_t.append(ax["EC"] or ax["NAME"] or sid)
            ecs_raw_t.append(";".join(ax.get("_ecs_raw") or []))
        print(f"  {len(src_ids)} {direction.upper()} entries")
        name_e = encode(name_t, "NAME")
        ec_e   = encode(ec_t,   "EC")
        out = EMB_DIR / f"{direction}_source_sapbert.npz"
        # Keys match step17_evaluate.evaluate_cell's reader: ids, name_emb, ec_emb, ecs_raw
        np.savez_compressed(
            out, ids=np.array(src_ids),
            name_emb=name_e, ec_emb=ec_e, ecs_raw=np.array(ecs_raw_t),
        )
        print(f"  → {out}  ({out.stat().st_size/1e6:.1f} MB)")

    print("\n✓ Done. Run `ontomap info` or `ontomap map --text 'Enoyl-CoA hydratase (EC 4.2.1.17)'` to verify.")


if __name__ == "__main__":
    main()
