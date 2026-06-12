"""Input-robustness tests for the free-text Pipeline.map_descriptions path.

These tests check that the pipeline degrades gracefully on edge-case
descriptions: empty strings, very long inputs, non-ASCII characters,
EC-with-dashes, multi-EC strings, name-only, and EC-only. They require
the bundled SapBERT weights, so they are skipped automatically when the
weights are not present (CI without weights still runs the lint pass).

Run only:
    pytest tests/test_input_robustness.py -m slow
or as part of the default run:
    pytest tests/
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the source tree is importable when tests are invoked without
# `pip install -e .` first.
ONTOMAP_SRC = Path("/scratch/vsetlur/ontology-mapping/ontomap")
if str(ONTOMAP_SRC) not in sys.path:
    sys.path.insert(0, str(ONTOMAP_SRC))


# ---- weight gate -------------------------------------------------------------

# The SapBERT weights live under <repo>/weights/sapbert/. The symlinked
# config.json is the cheapest probe — if it's there, the rest of the
# bundle is too.
_WEIGHTS = ONTOMAP_SRC / "weights" / "sapbert" / "config.json"
_HAS_WEIGHTS = _WEIGHTS.exists()

requires_weights = pytest.mark.skipif(
    not _HAS_WEIGHTS,
    reason="weights not available (expected at weights/sapbert/config.json)",
)


pytestmark = pytest.mark.slow


# ---- shared pipeline fixture (load once per module) -------------------------


@pytest.fixture(scope="module")
def pipe():
    """Load the SSO pipeline once per module; skip if weights are missing."""
    if not _HAS_WEIGHTS:
        pytest.skip("weights not available")
    from ontomap import Pipeline

    return Pipeline.from_pretrained(direction="sso", ec_augment=False)


# ---- helpers -----------------------------------------------------------------


def _assert_well_formed(result, query_id: str) -> None:
    """Common shape invariants for any MapResult, regardless of input."""
    assert result.query_id == query_id
    assert result.direction == "sso"
    # predictions must be a list (possibly empty); each entry is (str, float)
    assert isinstance(result.predictions, list)
    for entry in result.predictions:
        assert isinstance(entry, tuple) and len(entry) == 2
        rxn_id, score = entry
        assert isinstance(rxn_id, str) and rxn_id
        assert isinstance(score, float)
    # Latency must be a non-negative float — pipeline always sets it.
    assert isinstance(result.latency_ms, float)
    assert result.latency_ms >= 0.0


# ---- tests -------------------------------------------------------------------


@requires_weights
def test_empty_description_does_not_crash(pipe):
    """Empty string -> either zero predictions OR a graceful warning,
    but never an exception that escapes map_descriptions."""
    results = pipe.map_descriptions([""], ids=["empty"], top_k=10, verbose=False)
    assert len(results) == 1
    r = results[0]
    _assert_well_formed(r, "empty")
    # No EC should have been extracted from an empty string.
    assert r.source_ec in (None, "")


@requires_weights
def test_very_long_description(pipe):
    """A description > 500 chars should still produce a valid result.
    SapBERT will internally truncate to the model's max-len; that's fine."""
    enzyme = "Enoyl-CoA hydratase (EC 4.2.1.17)"
    padding = " involved in fatty acid beta-oxidation in the mitochondrial matrix"
    desc = enzyme + padding * 20  # ~1400 chars total
    assert len(desc) > 500
    results = pipe.map_descriptions([desc], ids=["long_q"], top_k=10, verbose=False)
    r = results[0]
    _assert_well_formed(r, "long_q")
    # The EC in the prefix must still be extracted despite the padding.
    assert r.source_ec == "4.2.1.17"
    # And we should get at least one candidate back.
    assert len(r.predictions) > 0


@requires_weights
def test_non_ascii_description(pipe):
    """Non-ASCII characters (greek letters, curly quotes) must not break
    tokenisation, EC extraction, or downstream encoding."""
    desc = "β-ketoacyl synthase / μ-glutamyltransferase ‘putative’ “isoform”"
    results = pipe.map_descriptions([desc], ids=["unicode_q"], top_k=10, verbose=False)
    r = results[0]
    _assert_well_formed(r, "unicode_q")
    # source_name should round-trip the unicode payload (pipeline shouldn't strip it).
    assert r.source_name is not None
    assert "β" in r.source_name or "μ" in r.source_name


@requires_weights
def test_ec_with_dash_subclass(pipe):
    """EC numbers with dashes (e.g. '1.2.-.-') indicate partial annotations.
    They should not crash the extractor; the matcher MAY treat them as a
    class-level hint (or simply not match) but must not blow up."""
    desc = "Putative oxidoreductase (EC 1.2.-.-)"
    results = pipe.map_descriptions([desc], ids=["partial_ec"], top_k=10, verbose=False)
    r = results[0]
    _assert_well_formed(r, "partial_ec")
    # Either source_ec is None (the strict-EC extractor didn't bite) or it
    # captured the prefix string. Either is acceptable as long as the call
    # returned cleanly.
    assert r.source_ec is None or "1.2" in r.source_ec


@requires_weights
def test_multiple_ec_in_description(pipe):
    """Some annotations list two EC numbers separated by '/' or ','.
    The pipeline should accept it (and ideally treat both as EC hints)."""
    desc = "Bifunctional aldehyde dehydrogenase (EC 1.2.1.3 / EC 1.2.1.5)"
    results = pipe.map_descriptions([desc], ids=["multi_ec"], top_k=10, verbose=False)
    r = results[0]
    _assert_well_formed(r, "multi_ec")
    # At least one of the two ECs should have been extracted into source_ec.
    assert r.source_ec is not None
    assert "1.2.1.3" in r.source_ec or "1.2.1.5" in r.source_ec
    # Pipeline must return at least one candidate.
    assert len(r.predictions) > 0


@requires_weights
def test_name_only(pipe):
    """No EC at all -> pipeline falls back to pure-name retrieval. Must
    still return candidates; source_ec must be None."""
    desc = "aldehyde dehydrogenase"
    results = pipe.map_descriptions([desc], ids=["name_only"], top_k=10, verbose=False)
    r = results[0]
    _assert_well_formed(r, "name_only")
    assert r.source_ec is None
    assert len(r.predictions) > 0


@requires_weights
def test_ec_only(pipe):
    """No name, just an EC. Pipeline should extract the EC and still
    return candidates (EC-priority bonus will favour EC-matching reactions)."""
    desc = "EC 1.2.1.3"
    results = pipe.map_descriptions([desc], ids=["ec_only"], top_k=10, verbose=False)
    r = results[0]
    _assert_well_formed(r, "ec_only")
    assert r.source_ec == "1.2.1.3"
    assert len(r.predictions) > 0


# ---- module-level smoke (no weights needed) ---------------------------------


def test_pipeline_imports_without_weights():
    """The public API surface must import even when weights are missing —
    so users can read docstrings, build typed wrappers, etc."""
    from ontomap import Pipeline, PipelineConfig  # noqa: F401

    # Constructing a config never touches the disk.
    cfg = PipelineConfig(direction="sso", ec_augment=True)
    assert cfg.ec_augment is True
    assert cfg.direction == "sso"
