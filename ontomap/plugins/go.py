"""Filipe GO text retrieval plugin from an accepted immutable public artifact."""
from __future__ import annotations
import json
from pathlib import Path
import joblib
import numpy as np
from sklearn.preprocessing import normalize
from ontomap import __version__
from ontomap.runtime.artifacts import verify_manifest
from ontomap.runtime.schema import MappingQuery, MappingResult, Prediction

class FilipeGOPlugin:
    name = "go-text"
    version = "1.0.0"
    metadata = {"schema": "mapping-result-v1", "compatibility": {"input": "text only", "output": "MappingResult"}, "deprecation": None, "provenance": "manifest-backed artifact", "runtime": "offline", "artifact_version": "filipe-go-v1", "artifact_sha256": "5f6e8b9178177ca7f8ef1f4816d84700579ce58e2dafda2db36295ab774c3e86", "benchmark": "filipe-go-v1", "metric_schema": "filipe-go-v1.metrics"}
    def __init__(self, artifact_dir: Path | None = None) -> None:
        self.artifact_dir = artifact_dir or Path(__file__).resolve().parents[1] / "artifacts" / "filipe-go-v1"
        self._model = None
        self._manifest = None
    def _load(self) -> None:
        if self._model is None:
            self._manifest = verify_manifest(self.artifact_dir / "manifest.json")
            self._model = joblib.load(self.artifact_dir / "filipe_text_to_go.joblib")
    def map(self, query: MappingQuery) -> MappingResult:
        self._load(); model = self._model
        word = normalize(model["word_vectorizer"].transform([query.text]))
        char = normalize(model["char_vectorizer"].transform([query.text]))
        scores = ((word @ model["word_centroids"].T).toarray().ravel() + (char @ model["char_centroids"].T).toarray().ravel()) / 2
        # Stable secondary identifier sort makes equal score order deterministic.
        order = sorted(range(len(scores)), key=lambda index: (-float(scores[index]), str(model["labels"][index])))[:query.top_k]
        predictions = [Prediction(id=str(model["labels"][index]), score=float(scores[index]), rank=rank + 1) for rank, index in enumerate(order)]
        return MappingResult(query.query_id, predictions, {"method": self.name, "method_version": self.version,
            "implementation": type(self).__module__ + "." + type(self).__name__, "schema_version": 1,
            "artifact_version": self._manifest["artifact_version"], "artifact_sha256": self._manifest["files"]["filipe_text_to_go.joblib"]["sha256"],
            "model_version": self._manifest["model_version"], "benchmark": self._manifest["benchmark"],
            "metric": self._manifest["metric"], "compatibility": self._manifest["compatibility"],
            "training": self._manifest["training"], "runtime_version": __version__})
