#!/usr/bin/env python3
"""Download and symlink the ModelSEED reaction corpus + compound table.

After cloning the repo, run:

    python scripts/build_corpus.py

This pulls the canonical reactions.tsv + compounds.tsv from the official
ModelSEED biochemistry repository and places them under
`data/modelseed_corpus/`. Idempotent.

Optional: pass --patches to ALSO apply the bundled ec_numbers patches
(78 reactions; see data/modelseed_corpus_patches.csv and CHANGELOG v1.1.0).
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "data" / "modelseed_corpus"
PATCHES_CSV = REPO_ROOT / "data" / "modelseed_corpus_patches.csv"

URLS = {
    "reactions.tsv": "https://raw.githubusercontent.com/ModelSEED/ModelSEEDDatabase/master/Biochemistry/reactions.tsv",
    "compounds.tsv": "https://raw.githubusercontent.com/ModelSEED/ModelSEEDDatabase/master/Biochemistry/compounds.tsv",
}


def download(url: str, dst: Path) -> None:
    print(f"  fetching {url}")
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read()
    dst.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()[:12]
    print(f"  → {dst.name}  ({len(data)/1e6:.1f} MB, sha256 prefix {sha})")


def apply_patches(reactions_tsv: Path) -> int:
    if not PATCHES_CSV.exists():
        print(f"  no patches at {PATCHES_CSV} — skipping")
        return 0
    print(f"\n[patches] applying {PATCHES_CSV.name} to {reactions_tsv.name}")
    patches: dict[str, str] = {}
    with PATCHES_CSV.open() as f:
        for i, row in enumerate(csv.reader(f)):
            if i == 0: continue  # header
            if len(row) >= 3 and row[0]:
                patches[row[0]] = row[2]
    print(f"  loaded {len(patches)} patches")

    rows = []
    n_applied = 0
    with reactions_tsv.open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            if r["id"] in patches and not (r.get("ec_numbers") or "").strip():
                r["ec_numbers"] = patches[r["id"]]
                n_applied += 1
            rows.append(r)

    if rows:
        out = reactions_tsv.with_suffix(".patched.tsv")
        with out.open("w") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys(), delimiter="\t")
            w.writeheader()
            for r in rows:
                w.writerow(r)
        # replace the original
        reactions_tsv.unlink()
        out.rename(reactions_tsv)
    print(f"  applied {n_applied} patches in-place")
    return n_applied


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--patches", action="store_true",
                    help="ALSO apply the bundled ec_numbers patches (78 reactions)")
    args = ap.parse_args()

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Corpus dir: {CORPUS_DIR}")

    for fname, url in URLS.items():
        dst = CORPUS_DIR / fname
        if dst.exists():
            print(f"  ✓ {fname} exists ({dst.stat().st_size/1e6:.1f} MB) — skipping")
        else:
            download(url, dst)

    if args.patches:
        n = apply_patches(CORPUS_DIR / "reactions.tsv")
        print(f"\n✓ Applied {n} corpus EC patches.")

    print("\n✓ Done. Now run `python scripts/regen_embeddings.py` to compute SapBERT embeddings.")


if __name__ == "__main__":
    main()
