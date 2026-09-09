"""Compatibility adapter for the established reaction Pipeline."""
from __future__ import annotations
import warnings
from ontomap.runtime.schema import MappingQuery, MappingResult, Prediction
class ReactionPlugin:
    name, version = "reaction", "legacy-1"
    metadata = {"schema": "mapping-result-v1", "compatibility": {"input": "text", "output": "MappingResult"}, "deprecation": "use a versioned reaction plugin", "provenance": "legacy Pipeline", "runtime": "local"}
    def map(self, query: MappingQuery) -> MappingResult:
        warnings.warn("reaction@legacy-1 is deprecated; use go-text or a versioned reaction plugin", DeprecationWarning, stacklevel=2)
        from ontomap.pipeline import Pipeline
        result = Pipeline.from_pretrained().map_descriptions([query.text], ids=[query.query_id], top_k=query.top_k, verbose=False)[0]
        return MappingResult(query.query_id, [Prediction(identifier, float(score), rank + 1) for rank, (identifier, score) in enumerate(result.predictions)], {"method": self.name, "method_version": self.version, "compatibility": "legacy Pipeline adapter", "deprecated": True}, result.warnings)
