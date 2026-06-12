"""`ontomap fetch-models` — pre-download SapBERT + MedCPT to HF cache.

LoRA adapters are bundled in the package (`ontomap/weights/lora/{sso,ko}/`)
and don't need fetching.
"""

from __future__ import annotations

import time

# Pin SHAs at release time. None = use latest until we tag v0.1.0 with revisions.
SAPBERT_REPO = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
SAPBERT_REVISION = None
MEDCPT_REPO = "ncbi/MedCPT-Cross-Encoder"
MEDCPT_REVISION = None


def fetch_all(force: bool = False) -> dict:
    """Download SapBERT base + MedCPT cross-encoder to the HF cache. Return a summary."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise ImportError(
            "huggingface_hub not installed — try `pip install huggingface_hub`"
        ) from e

    out: dict = {"downloads": [], "errors": []}
    for repo, rev, label in [
        (SAPBERT_REPO, SAPBERT_REVISION, "SapBERT base"),
        (MEDCPT_REPO, MEDCPT_REVISION, "MedCPT cross-encoder"),
    ]:
        t0 = time.perf_counter()
        try:
            kwargs = {"repo_id": repo, "force_download": force}
            if rev:
                kwargs["revision"] = rev
            path = snapshot_download(**kwargs)
            out["downloads"].append({
                "label": label,
                "repo": repo,
                "revision_pinned": rev,
                "local_path": str(path),
                "elapsed_sec": round(time.perf_counter() - t0, 2),
            })
        except Exception as e:
            out["errors"].append({
                "label": label,
                "repo": repo,
                "error": f"{type(e).__name__}: {e}",
            })

    out["ok"] = not out["errors"]
    return out
