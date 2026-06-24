"""`ontomap info` — version + weight pins + device + memory + bundle check + smoke-test."""

from __future__ import annotations

import importlib
import os
import platform

from ontomap import __version__, _paths

# Keys the runtime requires inside target_sapbert.npz (see
# _helpers/step17_evaluate.load_base_cache). Validated by _asset_health.
_TARGET_CACHE_KEYS = ("ids", "name_emb", "ec_emb", "eq_emb", "pw_emb", "ecs_raw")


def _asset_health() -> dict:
    """Deep, shape-aware validation of the critical runtime assets.

    Goes beyond `_paths.check_bundle()` presence checks: confirms each asset is
    a real, readable file of the expected shape. This is what would have caught
    the deletion that emptied `data/embeddings/` while a stale symlink lingered.
    Every check is best-effort and self-contained — missing optional deps
    degrade to a skip, not a crash.
    """
    out: dict = {}

    # 1) runtime embedding cache — six keys, row-aligned
    npz = _paths.embeddings_dir() / "target_sapbert.npz"
    try:
        if not npz.exists():
            out["target_sapbert.npz"] = {"ok": False, "error": "missing"}
        else:
            import numpy as np

            arr = np.load(npz)
            missing = [k for k in _TARGET_CACHE_KEYS if k not in arr.files]
            if missing:
                out["target_sapbert.npz"] = {
                    "ok": False,
                    "error": f"missing keys {missing} (got {sorted(arr.files)})",
                }
            else:
                n = len(arr["ids"])
                aligned = all(len(arr[k]) == n for k in _TARGET_CACHE_KEYS[1:])
                out["target_sapbert.npz"] = (
                    {"ok": True, "rows": int(n)}
                    if aligned
                    else {"ok": False, "error": "row-misaligned keys"}
                )
    except Exception as e:  # noqa: BLE001 - report, never crash info
        out["target_sapbert.npz"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # 2) SSO/KO dictionaries — parse as JSON, non-empty
    import json

    for direction in ("sso", "ko"):
        key = f"{direction}_dictionary"
        try:
            p = _paths.dictionary_path(direction)
            if not p.exists():
                out[key] = {"ok": False, "error": "missing"}
                continue
            d = json.loads(p.read_text())
            out[key] = (
                {"ok": True, "entries": len(d)}
                if d
                else {"ok": False, "error": "empty"}
            )
        except Exception as e:  # noqa: BLE001
            out[key] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # 3) LoRA adapters — directory resolves to a non-empty real dir
    for direction in ("sso", "ko"):
        key = f"lora_{direction}"
        try:
            p = _paths.lora_dir(direction) / "lora_adapter"
            if not p.exists():
                out[key] = {"ok": False, "error": "missing"}
            elif not any(p.iterdir()):
                out[key] = {"ok": False, "error": "empty adapter dir"}
            else:
                out[key] = {"ok": True}
        except Exception as e:  # noqa: BLE001
            out[key] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    return out


def collect_info(run_smoke_test: bool = True) -> dict:
    """Return a JSON-able dict describing the installation + bundled artifacts."""
    out: dict = {
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "ontomap_home": str(_paths.home()),
        "cwd": os.getcwd(),
        "ok": True,
        "warnings": [],
    }

    # Torch + CUDA
    try:
        import torch
        out["torch"] = torch.__version__
        out["cuda_available"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            out["cuda_device"] = torch.cuda.get_device_name(0)
            out["cuda_mem_total_gib"] = round(
                torch.cuda.get_device_properties(0).total_memory / (1024**3), 2
            )
    except ImportError:
        out["torch"] = None
        out["cuda_available"] = False
        out["warnings"].append("torch not installed")
        out["ok"] = False

    # Optional packages
    for pkg in ("transformers", "sentence_transformers", "peft", "faiss", "huggingface_hub"):
        try:
            mod = importlib.import_module(pkg)
            out[f"{pkg}_version"] = getattr(mod, "__version__", "unknown")
        except ImportError:
            out[f"{pkg}_version"] = None
            out["warnings"].append(f"{pkg} not installed")
            out["ok"] = False

    # Bundle presence check (cheap; no hashing)
    bundle = _paths.check_bundle()
    n_total = len(bundle)
    n_ok = sum(1 for v in bundle.values() if v.get("ok"))
    out["bundle_total_files"] = n_total
    out["bundle_present_files"] = n_ok
    out["bundle_missing"] = [k for k, v in bundle.items() if not v.get("ok")]
    if n_ok == n_total:
        out["weights_status"] = f"bundled ({n_ok}/{n_total} artifacts present)"
    else:
        out["weights_status"] = (
            f"INCOMPLETE bundle ({n_ok}/{n_total}; "
            f"{n_total - n_ok} missing) — run `ontomap fetch-models` or check `ontomap info --verify-manifest`"
        )
        out["warnings"].append(f"bundle incomplete: missing {n_total - n_ok}/{n_total}")
        out["ok"] = False

    # Deep asset health — not just "path exists" but "real file of expected
    # shape". This is the early-warning that catches a deletion/corruption that
    # presence-checks miss (e.g. a dangling symlink or a wrong-format npz).
    health = _asset_health()
    out["asset_health"] = health
    bad = [k for k, v in health.items() if not v.get("ok")]
    if bad:
        out["asset_health_bad"] = bad
        for k in bad:
            out["warnings"].append(f"asset unhealthy: {k} — {health[k].get('error')}")
        out["ok"] = False

    if _paths.manifest_path().exists():
        out["weights_manifest"] = str(_paths.manifest_path())

    # Smoke test — import the pipeline class, check it instantiates
    if run_smoke_test:
        try:
            from ontomap import Pipeline, PipelineConfig
            cfg = PipelineConfig(direction="sso", device="cpu")
            pipe = Pipeline(cfg)
            assert pipe.config.direction == "sso"
            out["smoke_status"] = "PASS (pipeline class instantiates; full-load skipped)"
        except Exception as e:
            out["smoke_status"] = f"FAIL: {type(e).__name__}: {e}"
            out["ok"] = False

    return out


def verify_manifest_cmd() -> dict:
    """Wrap _paths.verify_manifest() with friendly logging."""
    return _paths.verify_manifest()
