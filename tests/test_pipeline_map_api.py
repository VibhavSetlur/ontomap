"""Tests for the v1.4.0 Pipeline.map(name=, ec=, notes=, tags=) structured API.

Most tests require model weights (skipped if unavailable). The text-composition
tests (input parsing, validation) are weight-free.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pytest


WEIGHTS_PRESENT = (REPO / "weights" / "sapbert" / "config.json").exists()


# ---------------------------------------------------------------------------
# Weight-free tests — just the text composition logic + validation
# ---------------------------------------------------------------------------

def _compose(name=None, ec=None, notes=None, tags=None):
    """Copy of the text-composition logic from Pipeline.map for unit testing."""
    parts = []
    if name and name.strip():
        parts.append(name.strip())
    if ec and ec.strip():
        ec = ec.strip()
        if not ec.lower().startswith("ec"):
            ec = f"EC {ec}"
        if parts:
            parts[-1] = f"{parts[-1]} ({ec})"
        else:
            parts.append(ec)
    if tags:
        tag_text = "; ".join(t.strip() for t in tags if t and t.strip())
        if tag_text:
            parts.append(f"[{tag_text}]")
    if notes and notes.strip():
        parts.append(f"({notes.strip()})")
    return " ".join(parts) if parts else None


class TestTextComposition:
    def test_name_and_ec(self):
        assert _compose(name="Aldehyde dehydrogenase", ec="1.2.1.3") == \
            "Aldehyde dehydrogenase (EC 1.2.1.3)"

    def test_name_only(self):
        assert _compose(name="Aldehyde dehydrogenase") == "Aldehyde dehydrogenase"

    def test_ec_only_bare(self):
        assert _compose(ec="1.2.1.3") == "EC 1.2.1.3"

    def test_ec_only_with_prefix(self):
        assert _compose(ec="EC 1.2.1.3") == "EC 1.2.1.3"

    def test_ec_only_with_colon(self):
        # "EC:1.2.1.3" — startswith("ec") is true so we leave it
        assert _compose(ec="EC:1.2.1.3") == "EC:1.2.1.3"

    def test_name_ec_tags(self):
        out = _compose(name="Aldehyde dehydrogenase", ec="1.2.1.3",
                       tags=["putative", "partial"])
        assert "Aldehyde dehydrogenase (EC 1.2.1.3)" in out
        assert "[putative; partial]" in out

    def test_name_ec_notes(self):
        out = _compose(name="Aldehyde dehydrogenase", ec="1.2.1.3",
                       notes="from Acidovorax 3H11")
        assert "Aldehyde dehydrogenase (EC 1.2.1.3)" in out
        assert "(from Acidovorax 3H11)" in out

    def test_dash_ec(self):
        # subclass EC with dash
        assert _compose(name="Cytochrome", ec="1.10.3.-") == "Cytochrome (EC 1.10.3.-)"

    def test_whitespace_stripped(self):
        assert _compose(name="  Aldehyde dehydrogenase  ", ec="  1.2.1.3  ") == \
            "Aldehyde dehydrogenase (EC 1.2.1.3)"

    def test_empty_strings_treated_as_missing(self):
        assert _compose(name="", ec="1.2.1.3") == "EC 1.2.1.3"
        assert _compose(name="Aldehyde dehydrogenase", ec="") == "Aldehyde dehydrogenase"

    def test_empty_tags_dropped(self):
        out = _compose(name="X", tags=["", " ", None])
        assert out == "X"  # no [] for empty tags

    def test_nothing_returns_none(self):
        assert _compose() is None
        assert _compose(name="", ec="") is None


# ---------------------------------------------------------------------------
# Weight-required tests — require downloaded SapBERT + MedCPT
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not WEIGHTS_PRESENT, reason="weights/sapbert not present (run scripts/setup.sh)")
class TestPipelineMap:
    @pytest.fixture(scope="class")
    def pipe(self):
        from ontomap import Pipeline
        return Pipeline.from_pretrained(direction="sso")

    def test_validation_empty(self, pipe):
        with pytest.raises(ValueError, match="at least one of name, ec, notes, tags"):
            pipe.map()
        with pytest.raises(ValueError):
            pipe.map(name="", ec="", notes="", tags=[])

    def test_name_and_ec(self, pipe):
        r = pipe.map(name="Aldehyde dehydrogenase", ec="1.2.1.3", id="t1", top_k=3)
        assert r.query_id == "t1"
        assert r.source_ec == "1.2.1.3"
        assert len(r.predictions) == 3
        assert all(rxn.startswith("rxn") for rxn, _ in r.predictions)

    def test_name_only(self, pipe):
        r = pipe.map(name="Aldehyde dehydrogenase", id="t2", top_k=3)
        assert r.source_ec is None
        assert len(r.predictions) == 3

    def test_ec_only(self, pipe):
        r = pipe.map(ec="1.2.1.3", id="t3", top_k=3)
        assert r.source_ec == "1.2.1.3"
        assert len(r.predictions) == 3

    def test_tags_dont_break(self, pipe):
        r = pipe.map(name="Aldehyde dehydrogenase", ec="1.2.1.3",
                     tags=["putative", "partial"], id="t4", top_k=3)
        assert r.source_ec == "1.2.1.3"
        # the tags should be in source_name but stripped from EC parsing
        assert "putative" in (r.source_name or "")

    def test_ec_match_level_populated(self, pipe):
        r = pipe.map(name="Enoyl-CoA hydratase", ec="4.2.1.17", id="t5", top_k=3)
        meta = r.reaction_meta.get(r.predictions[0][0], {})
        # ec_match_level should be 0, 1, or 2 — populated by v1.3.0
        assert "ec_match_level" in meta
        assert meta["ec_match_level"] in (0, 1, 2)

    def test_confidence_band_on_top1(self, pipe):
        r = pipe.map(name="Enoyl-CoA hydratase", ec="4.2.1.17", id="t6", top_k=3)
        top1_meta = r.reaction_meta.get(r.predictions[0][0], {})
        assert top1_meta.get("confidence_band") in ("high", "medium", "low")
        assert "top1_margin" in top1_meta
