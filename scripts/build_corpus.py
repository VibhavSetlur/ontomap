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
import json
import os
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "data" / "modelseed_corpus"
PATCHES_CSV = REPO_ROOT / "data" / "modelseed_corpus_patches.csv"

MODELSEED_COMMIT = "194ac8afe48f8a606c0dd07ba3c7af10c02ba2fd"
_BIO = f"https://raw.githubusercontent.com/ModelSEED/ModelSEEDDatabase/{MODELSEED_COMMIT}/Biochemistry"
LICENSE_URL = "https://raw.githubusercontent.com/ModelSEED/ModelSEEDDatabase/master/LICENSE"
MANIFEST = CORPUS_DIR / "manifest.json"
URLS = {
    "reactions.tsv": f"{_BIO}/reactions.tsv",
    "compounds.tsv": f"{_BIO}/compounds.tsv",
}
# Alias tables the reaction pipeline reads (ECs / pathways / alt-names per
# reaction; aliases for cross-refs). Without these `regen_embeddings.py` and
# the runtime's multi-axis render cannot build the EC / PATHWAY / NAME axes.
ALIAS_FILES = [
    "Unique_ModelSEED_Reaction_ECs.txt",
    "Unique_ModelSEED_Reaction_Pathways.txt",
    "Unique_ModelSEED_Reaction_Names.txt",
    "Unique_ModelSEED_Reaction_Aliases.txt",
    "Unique_ModelSEED_Compound_Names.txt",
    "Unique_ModelSEED_Compound_Aliases.txt",
]
ALIAS_URLS = {f"Aliases/{name}": f"{_BIO}/Aliases/{name}" for name in ALIAS_FILES}


def download(url: str, dst: Path) -> str:
    print(f"  fetching {url}")
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read()
    dst.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    print(f"  → {dst.name}  ({len(data)/1e6:.1f} MB, sha256 {digest})")
    return digest


def write_manifest(files: dict[str, dict[str, str]]) -> None:
    MANIFEST.write_text(json.dumps({
        "schema_version": 1, "source": "ModelSEEDDatabase",
        "commit": MODELSEED_COMMIT, "license_url": LICENSE_URL,
        "external_records_only": True, "files": files,
    }, indent=2) + "\n")


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
    global CORPUS_DIR, MANIFEST
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--patches", action="store_true",
                    help="ALSO apply the bundled ec_numbers patches (78 reactions)")
    ap.add_argument("--cache-dir", type=Path, default=CORPUS_DIR,
                    help="ignored external cache destination (default: data/modelseed_corpus)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the pinned acquisition manifest inputs without downloading")
    args = ap.parse_args()

    CORPUS_DIR = args.cache_dir
    MANIFEST = CORPUS_DIR / "manifest.json"
    if args.dry_run:
        print(json.dumps({"commit": MODELSEED_COMMIT, "license_url": LICENSE_URL,
                          "external_records_only": True,
                          "files": {**URLS, **ALIAS_URLS}}, indent=2))
        return
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Corpus dir: {CORPUS_DIR}")

    manifest_files: dict[str, dict[str, str]] = {}
    for fname, url in URLS.items():
        dst = CORPUS_DIR / fname
        if dst.exists():
            digest = hashlib.sha256(dst.read_bytes()).hexdigest()
            print(f"  ✓ {fname} exists ({dst.stat().st_size/1e6:.1f} MB) — skipping")
        else:
            digest = download(url, dst)
        manifest_files[fname] = {"url": url, "sha256": digest}

    # Alias tables (ECs / pathways / names / aliases) — required by the
    # reaction pipeline's multi-axis render + regen_embeddings.py.
    (CORPUS_DIR / "Aliases").mkdir(parents=True, exist_ok=True)
    for relpath, url in ALIAS_URLS.items():
        dst = CORPUS_DIR / relpath
        if dst.exists():
            digest = hashlib.sha256(dst.read_bytes()).hexdigest()
            print(f"  ✓ {relpath} exists — skipping")
        else:
            digest = download(url, dst)
        manifest_files[relpath] = {"url": url, "sha256": digest}

    if args.patches:
        n = apply_patches(CORPUS_DIR / "reactions.tsv")
        print(f"\n✓ Applied {n} corpus EC patches.")
        manifest_files["reactions.tsv"]["sha256"] = hashlib.sha256((CORPUS_DIR / "reactions.tsv").read_bytes()).hexdigest()

    write_manifest(manifest_files)
    print(f"  wrote reproducibility manifest: {MANIFEST}")
    print("\n✓ Done. Now run `python scripts/regen_embeddings.py` to compute SapBERT embeddings.")


if __name__ == "__main__":
    main()
