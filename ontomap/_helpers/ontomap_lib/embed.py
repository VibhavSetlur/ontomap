"""Encoder + FAISS index wrappers.

Thin layer over sentence-transformers and faiss to keep the rest of the code
agnostic to model and index choice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np


_MODEL_CACHE: dict[str, object] = {}


def get_encoder(name: str = "biolord"):
    """Return a sentence-transformers model, lazy-loaded and cached."""
    from sentence_transformers import SentenceTransformer

    if name in _MODEL_CACHE:
        return _MODEL_CACHE[name]

    if name == "biolord":
        hf_id = "FremyCompany/BioLORD-2023"
    elif name == "sapbert":
        hf_id = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
    elif name == "minilm":
        hf_id = "sentence-transformers/all-MiniLM-L6-v2"
    else:
        hf_id = name

    model = SentenceTransformer(hf_id)
    _MODEL_CACHE[name] = model
    return model


def encode_texts(texts: list[str], model_name: str = "biolord", batch_size: int = 32) -> np.ndarray:
    """Encode a list of texts. Returns L2-normalized (N, dim) float32 array."""
    model = get_encoder(model_name)
    embs = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return embs.astype("float32")


def encode_dict(items: dict[str, str], model_name: str = "biolord", batch_size: int = 32) -> tuple[list[str], np.ndarray]:
    """Encode a dict {id: text}. Returns (ids_list, embeddings_array) in parallel order."""
    ids = list(items.keys())
    texts = [items[i] for i in ids]
    embs = encode_texts(texts, model_name=model_name, batch_size=batch_size)
    return ids, embs


def build_index(embeddings: np.ndarray):
    """Build a FAISS IndexFlatIP. Assumes embeddings are already L2-normalized."""
    import faiss

    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)
    return index


def save_artifact(path: Path, ids: list[str], embeddings: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path.with_suffix(".npy"), embeddings)
    with path.with_suffix(".ids.json").open("w") as f:
        json.dump(ids, f)


def load_artifact(path: Path) -> tuple[list[str], np.ndarray]:
    embs = np.load(path.with_suffix(".npy"))
    with path.with_suffix(".ids.json").open() as f:
        ids = json.load(f)
    return ids, embs
