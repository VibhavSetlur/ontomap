"""Bundled-artifact path resolver.

Looks for `weights/` and `data/` relative to the installed package first,
then falls back to `ONTOMAP_HOME` env var, then to the project source
layout. Use these helpers so the rest of the code never hardcodes paths.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

Direction = Literal["sso", "ko"]


def package_root() -> Path:
    """Path to the `ontomap` package directory (where __init__.py lives)."""
    return Path(__file__).resolve().parent


def install_root() -> Path:
    """Path to the `ontomap/` distribution folder (parent of the package).

    The bundled weights + data sit here, NOT inside the python package, so
    that an editable install (`pip install -e .`) sees the symlinks and a
    wheel-built install picks them up via setuptools `package-data`.
    """
    return package_root().parent


def home() -> Path:
    """Resolve the bundled-artifact root. Order of precedence:

    1. `$ONTOMAP_HOME` env var
    2. `install_root()` if `install_root()/weights/MANIFEST.txt` exists
       (the bundled case — `weights/` and `data/` next to the package)
    3. `install_root()` regardless (best-effort fallback)
    """
    env = os.environ.get("ONTOMAP_HOME")
    if env:
        return Path(env)
    root = install_root()
    return root


def weights_dir() -> Path:
    return home() / "weights"


def data_dir() -> Path:
    return home() / "data"


def sapbert_dir() -> Path:
    return weights_dir() / "sapbert"


def medcpt_dir() -> Path:
    return weights_dir() / "medcpt"


def lora_dir(direction: Direction) -> Path:
    return weights_dir() / "lora" / direction


def swept_weights_path() -> Path:
    return weights_dir() / "swept_weights.json"


def manifest_path() -> Path:
    return weights_dir() / "MANIFEST.txt"


def embeddings_dir() -> Path:
    return data_dir() / "embeddings"


def modelseed_corpus_dir() -> Path:
    return data_dir() / "modelseed_corpus"


def dictionary_path(direction: Direction) -> Path:
    name = "SSO_dictionary.json" if direction == "sso" else "KO_dictionary.json"
    return data_dir() / "dictionaries" / name


def gold_mapping_path(direction: Direction) -> Path:
    """Curated gold mapping file — bundled for reproducibility/regression
    tests, not strictly required at inference time."""
    name = "SSO_reactions.json" if direction == "sso" else "kegg_95_0_ko_seed.tsv"
    return data_dir() / "dictionaries" / name


def check_bundle() -> dict:
    """Cheap presence + size check of every expected bundled artifact.
    Returns a dict suitable for serialising in `ontomap info`."""
    artifacts = {
        "sapbert/config.json":      sapbert_dir() / "config.json",
        "sapbert/model.safetensors": sapbert_dir() / "model.safetensors",
        "sapbert/tokenizer_config.json": sapbert_dir() / "tokenizer_config.json",
        "sapbert/vocab.txt":        sapbert_dir() / "vocab.txt",
        "medcpt/config.json":       medcpt_dir() / "config.json",
        "medcpt/pytorch_model.bin": medcpt_dir() / "pytorch_model.bin",
        "medcpt/tokenizer.json":    medcpt_dir() / "tokenizer.json",
        "lora/sso/lora_adapter":    lora_dir("sso") / "lora_adapter",
        "lora/ko/lora_adapter":     lora_dir("ko") / "lora_adapter",
        "swept_weights.json":       swept_weights_path(),
        "MANIFEST.txt":             manifest_path(),
        "data/embeddings/target_sapbert.npz":     embeddings_dir() / "target_sapbert.npz",
        "data/embeddings/sso_source_sapbert.npz": embeddings_dir() / "sso_source_sapbert.npz",
        "data/embeddings/ko_source_sapbert.npz":  embeddings_dir() / "ko_source_sapbert.npz",
        "data/modelseed_corpus/reactions.tsv":    modelseed_corpus_dir() / "reactions.tsv",
        "data/modelseed_corpus/compounds.tsv":    modelseed_corpus_dir() / "compounds.tsv",
        "data/dictionaries/SSO_dictionary.json":  dictionary_path("sso"),
        "data/dictionaries/KO_dictionary.json":   dictionary_path("ko"),
    }
    out = {}
    for k, p in artifacts.items():
        if p.exists():
            try:
                size = p.stat().st_size if p.is_file() else None
                out[k] = {"ok": True, "size": size, "path": str(p)}
            except OSError as e:
                out[k] = {"ok": False, "error": str(e), "path": str(p)}
        else:
            out[k] = {"ok": False, "missing": True, "path": str(p)}
    return out


def verify_manifest() -> dict:
    """Re-hash every file in MANIFEST.txt and compare to the recorded SHA-256."""
    import hashlib
    mp = manifest_path()
    if not mp.exists():
        return {"ok": False, "error": f"manifest not found at {mp}"}

    entries = []
    for line in mp.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Format: <sha>  <bytes>  <relpath>  [→ ...]
        parts = line.split(None, 3)
        if len(parts) < 3:
            continue
        sha_expected = parts[0]
        try:
            size_expected = int(parts[1].replace(",", ""))
        except ValueError:
            continue
        relpath = parts[2]
        entries.append((sha_expected, size_expected, relpath))

    results = []
    n_ok = 0
    for sha_expected, size_expected, rel in entries:
        p = install_root() / rel
        if not p.exists():
            results.append({"path": rel, "status": "MISSING"})
            continue
        target = p.resolve() if p.is_symlink() else p
        if not target.is_file():
            continue
        h = hashlib.sha256()
        with target.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        actual = h.hexdigest()
        actual_size = target.stat().st_size
        if actual == sha_expected and actual_size == size_expected:
            results.append({"path": rel, "status": "OK"})
            n_ok += 1
        else:
            results.append({
                "path": rel, "status": "BAD",
                "expected_sha": sha_expected, "actual_sha": actual,
                "expected_size": size_expected, "actual_size": actual_size,
            })

    return {
        "ok": n_ok == len(results),
        "n_total": len(results),
        "n_ok": n_ok,
        "n_bad": sum(1 for r in results if r["status"] == "BAD"),
        "n_missing": sum(1 for r in results if r["status"] == "MISSING"),
        "results": results,
    }
