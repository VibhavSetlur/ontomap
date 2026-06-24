#!/usr/bin/env python3
"""Ensure the SapBERT-LoRA adapters are present under weights/lora/{sso,ko}/.

The trained LoRA adapters (~11 MB each) power the annotation → reaction
Pipeline (capability 2). As of v1.6.0 they are **vendored as real files** in a
maintainer checkout, so on this machine this script is a no-op. It exists for
two cases:

  1. A fresh clone where `weights/lora/{sso,ko}/lora_adapter/` is empty and the
     adapters live in a sibling research workspace — symlink them in.
  2. Re-pointing after the workspace adapters move.

Resolution order for each direction's source adapter:
  $ONTOMAP_LORA_<DIR>           (explicit override, e.g. ONTOMAP_LORA_SSO=/path)
  <workspace>/17_sapbert_lora/outputs/adapters/sapbert-lora-<dir>-splitC/

Idempotent. Never overwrites a real (non-symlink) adapter already in place.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LORA_DIR = REPO_ROOT / "weights" / "lora"

# Best-effort guess at the research workspace that holds the trained adapters.
# Override per-direction with $ONTOMAP_LORA_SSO / $ONTOMAP_LORA_KO.
WORKSPACE_ADAPTERS = (
    REPO_ROOT.parent / "workspace" / "17_sapbert_lora" / "outputs" / "adapters"
)
SUBDIRS = {
    "sso": "sapbert-lora-sso-splitC",
    "ko": "sapbert-lora-ko-splitC",
}
# Files that make up a complete adapter directory entry.
LINK_ITEMS = ["lora_adapter", "train_config.json", "val_metrics.json"]


def _is_present(p: Path) -> bool:
    """A real file/dir, or a symlink that resolves to one."""
    return p.exists() and (not p.is_symlink() or p.resolve().exists())


def link_direction(direction: str) -> bool:
    dst_dir = LORA_DIR / direction
    adapter = dst_dir / "lora_adapter"
    if _is_present(adapter) and not adapter.is_symlink():
        print(f"[{direction}] lora_adapter already a real directory — skip")
        return True
    if _is_present(adapter) and adapter.is_symlink():
        print(f"[{direction}] lora_adapter symlink resolves OK — skip")
        return True

    env = os.environ.get(f"ONTOMAP_LORA_{direction.upper()}")
    src_dir = Path(env) if env else (WORKSPACE_ADAPTERS / SUBDIRS[direction])
    if not src_dir.exists():
        print(
            f"[{direction}] NO SOURCE: {src_dir} not found. "
            f"Set ONTOMAP_LORA_{direction.upper()}=<adapter dir> or request the "
            f"adapters from the maintainer (see SETUP_ASSETS.md)."
        )
        return False

    dst_dir.mkdir(parents=True, exist_ok=True)
    linked = 0
    for item in LINK_ITEMS:
        src = src_dir / item
        if not src.exists():
            print(f"[{direction}] WARN: {src.name} not in source; skipping")
            continue
        dst = dst_dir / item
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src.resolve())
        linked += 1
        print(f"[{direction}] linked {dst.name} -> {src}")
    return linked > 0


def main() -> int:
    print(f"weights/lora dir: {LORA_DIR}")
    ok = all([link_direction("sso"), link_direction("ko")])
    if ok:
        print("\n✓ LoRA adapters present. Verify with `ontomap info`.")
        return 0
    print(
        "\n! One or more adapters missing. The reaction Pipeline (capability 2) "
        "will not load until they are provided."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
