"""The runtime embedding cache must carry the keys the runtime reads.

Root-cause regression guard for v1.6.0. In v1.5.x, `scripts/regen_embeddings.py`
wrote npz keys `name/ec/equation/pathway`, but the runtime loader
`step17_evaluate.load_base_cache()` reads `name_emb/ec_emb/eq_emb/pw_emb/ecs_raw`.
A regenerated cache loaded fine in the script but crashed at `ontomap map` time.
These tests assert the contract from both ends so the mismatch cannot return.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ontomap import _paths

pytestmark = pytest.mark.smoke

# The exact keys the runtime loader requires.
RUNTIME_KEYS = ("ids", "name_emb", "ec_emb", "eq_emb", "pw_emb", "ecs_raw")


def test_loader_and_regen_agree_on_keys():
    """The loader's read keys and the regen script's write keys must match.

    Pure source-of-truth check — no large files needed. Reads the literal key
    list from the regen script and asserts it equals what the loader pulls.
    """
    regen = (Path(_paths.install_root()) / "scripts" / "regen_embeddings.py").read_text()
    # the regen script defines TARGET_CACHE_KEYS as the contract
    assert "TARGET_CACHE_KEYS" in regen
    for k in RUNTIME_KEYS:
        assert f'"{k}"' in regen, f"regen script no longer references key {k}"
    # the loader reads these exact bracketed keys
    loader = (
        Path(_paths.package_root()) / "_helpers" / "step17_evaluate.py"
    ).read_text()
    for k in ("ids", "name_emb", "ec_emb", "eq_emb", "pw_emb", "ecs_raw"):
        assert f'arr["{k}"]' in loader, f"loader no longer reads key {k}"


def test_bundled_cache_has_runtime_keys():
    """If the bundled cache is present, it must have all six keys, row-aligned."""
    npz = _paths.embeddings_dir() / "target_sapbert.npz"
    if not npz.exists():
        pytest.skip("bundled target_sapbert.npz not present (run scripts/setup.sh)")
    arr = np.load(npz)
    missing = [k for k in RUNTIME_KEYS if k not in arr.files]
    assert not missing, f"bundled cache missing runtime keys {missing}"
    n = len(arr["ids"])
    for k in RUNTIME_KEYS[1:]:
        assert len(arr[k]) == n, f"key {k} row-misaligned ({len(arr[k])} vs {n})"
