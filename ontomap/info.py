"""`ontomap info` — version + weight pins + device + memory + bundle check + smoke-test."""

from __future__ import annotations

import importlib
import os
import platform
from pathlib import Path

from ontomap import __version__
from ontomap import _paths


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
