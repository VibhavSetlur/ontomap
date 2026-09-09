"""Versioned public API for local plugin inference."""
from __future__ import annotations

from collections.abc import Sequence

from ontomap.plugins import FilipeFilteredGOPlugin, FilipeGOPlugin, ReactionPlugin
from ontomap.runtime import MappingQuery, MappingResult, Registry


def default_registry() -> Registry:
    registry = Registry()
    registry.register(FilipeGOPlugin())
    registry.register(FilipeFilteredGOPlugin())
    registry.register(ReactionPlugin())
    return registry


def map_text(
    text: str,
    *,
    method: str = "go-text",
    version: str | None = None,
    query_id: str = "Q1",
    top_k: int = 20,
) -> MappingResult:
    """Map one text query through an explicitly versioned local method."""
    bundle = default_registry().resolve(method, version)
    return bundle.plugin.map(MappingQuery(text, query_id, top_k))


def map_batch(
    texts: Sequence[str],
    *,
    method: str = "go-text",
    version: str | None = None,
    query_ids: Sequence[str] | None = None,
    top_k: int = 20,
) -> list[MappingResult]:
    """Map text queries in input order using one resolved method/version.

    Each entry is validated with :class:`MappingQuery` before inference; invalid
    input raises the same ``ValidationError`` as :func:`map_text`.
    """
    text_values = list(texts)
    ids = list(query_ids) if query_ids is not None else [f"Q{index + 1}" for index in range(len(text_values))]
    if len(ids) != len(text_values):
        from ontomap.runtime import ValidationError
        raise ValidationError("invalid_query_ids", "query_ids must match texts length", "query_ids")
    bundle = default_registry().resolve(method, version)
    queries = [MappingQuery(text, query_id, top_k) for text, query_id in zip(text_values, ids)]
    return [bundle.plugin.map(query) for query in queries]


__all__ = ["default_registry", "map_batch", "map_text"]
