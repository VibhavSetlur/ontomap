"""Cross-encoder reranking.

Default reranker: NCBI MedCPT-Cross-Encoder (biomedical IR, trained on
PubMed click logs). It scores (query, candidate) pairs jointly using a
single BERT pass, which is more expressive than the bi-encoder cosine
similarity used for first-stage retrieval.

Usage pattern: take top-K candidates from FAISS retrieval, re-encode each
(query, candidate) pair through the cross-encoder, re-sort by score.
"""

from __future__ import annotations

import numpy as np


_CE_CACHE: dict[str, object] = {}


def get_cross_encoder(name: str = "medcpt"):
    """Lazy-load a cross-encoder. Cached across calls."""
    from sentence_transformers import CrossEncoder

    if name in _CE_CACHE:
        return _CE_CACHE[name]

    if name == "medcpt":
        hf_id = "ncbi/MedCPT-Cross-Encoder"
        # MedCPT is a HuggingFace model that uses a custom forward, but it
        # works as a CrossEncoder if max_length is set. Use AutoModel approach.
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        import torch

        tokenizer = AutoTokenizer.from_pretrained(hf_id)
        model = AutoModelForSequenceClassification.from_pretrained(hf_id)
        model.eval()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = model.to(device)
        _CE_CACHE[name] = ("medcpt_raw", tokenizer, model, device)
        return _CE_CACHE[name]
    else:
        ce = CrossEncoder(name)
        _CE_CACHE[name] = ("sbert_ce", ce)
        return _CE_CACHE[name]


def score_pairs(pairs: list[tuple[str, str]], name: str = "medcpt", batch_size: int = 32) -> np.ndarray:
    """Score a list of (query, candidate) pairs. Returns array of scores (higher = better)."""
    import torch

    ce = get_cross_encoder(name)
    kind = ce[0]

    if kind == "medcpt_raw":
        _, tokenizer, model, device = ce
        scores = []
        with torch.no_grad():
            for i in range(0, len(pairs), batch_size):
                batch = pairs[i:i + batch_size]
                inputs = tokenizer(
                    [q for q, _ in batch],
                    [c for _, c in batch],
                    truncation=True,
                    padding=True,
                    return_tensors="pt",
                    max_length=512,
                ).to(device)
                logits = model(**inputs).logits.squeeze(-1)
                scores.extend(logits.cpu().numpy().tolist())
        return np.array(scores, dtype="float32")
    else:
        _, ce_obj = ce
        return np.array(ce_obj.predict(pairs, batch_size=batch_size, show_progress_bar=False), dtype="float32")


def rerank(
    query_text: str,
    candidate_ids: list[str],
    candidate_texts: list[str],
    name: str = "medcpt",
    batch_size: int = 32,
) -> tuple[list[str], list[float]]:
    """Score (query_text, each candidate_text), return (sorted_ids, sorted_scores)."""
    if not candidate_ids:
        return [], []
    pairs = [(query_text, c) for c in candidate_texts]
    scores = score_pairs(pairs, name=name, batch_size=batch_size)
    order = np.argsort(-scores)
    return [candidate_ids[i] for i in order], [float(scores[i]) for i in order]
