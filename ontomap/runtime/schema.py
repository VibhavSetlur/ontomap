"""Validated, JSON-serializable contracts for the local mapping runtime."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any


class ValidationError(ValueError):
    """A caller-facing validation failure with a stable machine-readable code."""
    def __init__(self, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.code, self.field = code, field
    def to_dict(self) -> dict[str, str | None]:
        return {"error": self.code, "message": str(self), "field": self.field}


@dataclass(frozen=True)
class MappingQuery:
    text: str
    query_id: str = "Q1"
    top_k: int = 20
    include_terms: bool = False
    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValidationError("invalid_text", "text must be a non-empty string", "text")
        if not isinstance(self.query_id, str) or not self.query_id:
            raise ValidationError("invalid_query_id", "query_id must be a non-empty string", "query_id")
        if not isinstance(self.top_k, int) or self.top_k < 1:
            raise ValidationError("invalid_top_k", "top_k must be a positive integer", "top_k")


@dataclass(frozen=True)
class Prediction:
    id: str
    score: float
    rank: int
    term: str | None = None


@dataclass
class MappingResult:
    query_id: str
    predictions: list[Prediction]
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    def to_dict(self) -> dict[str, Any]:
        return {"query_id": self.query_id, "predictions": [asdict(p) for p in self.predictions],
                "provenance": self.provenance, "warnings": self.warnings}
