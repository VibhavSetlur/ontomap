import json
from pathlib import Path
import pytest
from ontomap.api import default_registry, map_text
from ontomap.runtime.artifacts import verify_manifest
from ontomap.runtime.schema import MappingQuery, ValidationError


def test_registry_resolves_explicit_versions():
    registry = default_registry()
    assert registry.resolve("go-text", "1.0.0").method == "go-text"
    with pytest.raises(ValidationError) as exc:
        registry.resolve("missing")
    assert exc.value.code == "unknown_method_version"


def test_go_artifact_is_verified_and_metadata_is_public_safe():
    manifest = verify_manifest(Path(__file__).parents[1] / "ontomap/artifacts/filipe-go-v1/manifest.json")
    assert manifest["training"]["records"] == 104032
    assert manifest["metric"]["top20"] == pytest.approx(0.9501709631564793)


def test_go_text_is_deterministic_and_batched_contract():
    one = map_text("mitochondrial ATP synthase assembly", query_id="one", top_k=3)
    two = map_text("mitochondrial ATP synthase assembly", query_id="two", top_k=3)
    assert [p.id for p in one.predictions] == [p.id for p in two.predictions]
    assert [p.rank for p in one.predictions] == [1, 2, 3]
    assert one.provenance["artifact_version"] == "filipe-go-v1"
    assert one.provenance["metric"]["limitation"].startswith("Scores are descriptive")


def test_validation_is_structured():
    with pytest.raises(ValidationError) as exc:
        MappingQuery("", top_k=1)
    assert exc.value.to_dict()["error"] == "invalid_text"


def test_go_batch_is_ordered_and_uses_shared_validation():
    from ontomap.api import map_batch

    results = map_batch(["DNA repair helicase", "mitochondrial ATP synthase assembly"],
                        version="1.0.0", query_ids=["first", "second"], top_k=2)
    assert [result.query_id for result in results] == ["first", "second"]
    assert all(len(result.predictions) == 2 for result in results)
    with pytest.raises(ValidationError) as exc:
        map_batch(["valid", ""], query_ids=["one", "two"])
    assert exc.value.code == "invalid_text"


def test_batch_reaction_resolves_before_asset_dependent_inference():
    from ontomap.api import map_batch

    with pytest.raises(ValidationError) as exc:
        map_batch(["text"], method="reaction", version="missing")
    assert exc.value.code == "unknown_method_version"
    with pytest.raises(ValidationError) as exc:
        map_batch(["text"], query_ids=[])
    assert exc.value.code == "invalid_query_ids"
