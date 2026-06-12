#!/usr/bin/env python3
"""Download all HuggingFace models ontomap needs and symlink them into weights/.

After cloning the repo and `pip install -e .`, run this once:

    python scripts/download_models.py

It downloads:
  - cambridgeltl/SapBERT-from-PubMedBERT-fulltext  (~440 MB)
  - ncbi/MedCPT-Cross-Encoder                       (~440 MB)

and symlinks the cached files into `weights/sapbert/` and `weights/medcpt/`.

Idempotent — safe to re-run. Uses HF_HOME or ~/.cache/huggingface by default.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEIGHTS_DIR = REPO_ROOT / "weights"

MODELS = {
    "sapbert": {
        "hf_id": "cambridgeltl/SapBERT-from-PubMedBERT-fulltext",
        "files": ["config.json", "tokenizer_config.json", "vocab.txt",
                  "special_tokens_map.json", "model.safetensors"],
    },
    "medcpt": {
        "hf_id": "ncbi/MedCPT-Cross-Encoder",
        "files": ["config.json", "tokenizer_config.json", "vocab.txt",
                  "special_tokens_map.json", "tokenizer.json",
                  "pytorch_model.bin"],
    },
}


def download_and_link(name: str, spec: dict) -> None:
    print(f"\n[{name}] downloading {spec['hf_id']} …")
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("ERROR: pip install huggingface_hub")
        sys.exit(1)

    cache_dir = snapshot_download(repo_id=spec["hf_id"],
                                   allow_patterns=spec["files"] + ["*.json", "*.txt"])
    cache_dir = Path(cache_dir)
    print(f"  cached at: {cache_dir}")

    target = WEIGHTS_DIR / name
    target.mkdir(parents=True, exist_ok=True)
    for fname in spec["files"]:
        src = cache_dir / fname
        if not src.exists():
            # safetensors might be in a subdir or have a different name
            candidates = list(cache_dir.glob(f"**/{fname}"))
            if not candidates:
                print(f"  WARN: {fname} not found in cache; skipping")
                continue
            src = candidates[0]
        dst = target / fname
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src.resolve())
        print(f"  linked: {dst.name}")
    print(f"  → {target}")


def main():
    print(f"Repo root: {REPO_ROOT}")
    print(f"Weights dir: {WEIGHTS_DIR}")
    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    for name, spec in MODELS.items():
        download_and_link(name, spec)
    print("\n✓ Done. Run `python -c 'import ontomap; print(ontomap.__version__)'` to verify.")


if __name__ == "__main__":
    main()
