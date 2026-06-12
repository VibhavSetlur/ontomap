"""Unit tests for the EC-priority helpers (no model weights required).

These run in CI without the SapBERT/MedCPT downloads.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pytest

from ontomap._frozen_runtime import (
    _extract_query_ecs,
    _ec_match_bonus,
    _ec_augmented_candidates,
    EC_PRIORITY_BONUS,
)


class TestExtractQueryECs:
    def test_full_4level(self):
        assert _extract_query_ecs("Aldehyde dehydrogenase (EC 1.2.1.3)") == ["1.2.1.3"]

    def test_3level(self):
        assert _extract_query_ecs("(EC 4.2.1.-)") == ["4.2.1"]

    def test_bare_no_ec_prefix(self):
        assert _extract_query_ecs("1.2.1.3 dehydrogenase") == ["1.2.1.3"]

    def test_multiple_ecs(self):
        out = _extract_query_ecs("Transpeptidase (EC 2.4.1.129) (EC 3.4.16.-)")
        assert "2.4.1.129" in out and "3.4.16" in out

    def test_no_ec(self):
        assert _extract_query_ecs("aldehyde dehydrogenase") == []

    def test_empty(self):
        assert _extract_query_ecs("") == []
        assert _extract_query_ecs(None) == []  # type: ignore

    def test_no_dedup_issue(self):
        out = _extract_query_ecs("EC 1.2.1.3 and again EC 1.2.1.3")
        assert out == ["1.2.1.3"]


class TestECMatchBonus:
    def test_exact_match(self):
        assert _ec_match_bonus(["1.2.1.3"], "1.2.1.3") == EC_PRIORITY_BONUS

    def test_pipe_separated_candidate(self):
        assert _ec_match_bonus(["1.2.1.3"], "1.2.1.3|1.2.1.5") == EC_PRIORITY_BONUS

    def test_prefix_match(self):
        # query 3-level matches 4-level candidate
        assert _ec_match_bonus(["1.10.3"], "1.10.3.10") == EC_PRIORITY_BONUS

    def test_no_match(self):
        assert _ec_match_bonus(["1.2.1.3"], "3.4.21.4") == 0.0

    def test_empty_inputs(self):
        assert _ec_match_bonus([], "1.2.1.3") == 0.0
        assert _ec_match_bonus(["1.2.1.3"], "") == 0.0
        assert _ec_match_bonus(["1.2.1.3"], None) == 0.0  # type: ignore

    def test_custom_bonus(self):
        assert _ec_match_bonus(["1.2.1.3"], "1.2.1.3", bonus=0.5) == 0.5


class TestECAugmentedCandidates:
    def _meta(self, pairs):
        return {rid: {"ec_numbers": ec} for rid, ec in pairs}

    def test_basic_match(self):
        meta = self._meta([("rxn1", "1.2.1.3"), ("rxn2", "3.4.5.6"), ("rxn3", "1.2.1.3|1.2.1.5")])
        out = _ec_augmented_candidates(["1.2.1.3"], meta, already=set())
        assert "rxn1" in out and "rxn3" in out and "rxn2" not in out

    def test_exclude_already_present(self):
        meta = self._meta([("rxn1", "1.2.1.3"), ("rxn3", "1.2.1.3|1.2.1.5")])
        out = _ec_augmented_candidates(["1.2.1.3"], meta, already={"rxn1"})
        assert "rxn1" not in out
        assert "rxn3" in out

    def test_max_extra_cap(self):
        meta = self._meta([(f"rxn{i}", "1.2.1.3") for i in range(50)])
        out = _ec_augmented_candidates(["1.2.1.3"], meta, already=set(), max_extra=10)
        assert len(out) == 10

    def test_empty_query_ecs(self):
        meta = self._meta([("rxn1", "1.2.1.3")])
        out = _ec_augmented_candidates([], meta, already=set())
        assert out == []
