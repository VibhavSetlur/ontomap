"""Regression test: `map --format sqlite` must be a first-class, accepted choice.

Before this fix, `ontomap/cli.py`'s `map` subparser `--format` enum omitted
"sqlite" even though `io.write_results` / `io.write_sqlite` already supported
it (reachable only via `--output x.sqlite` extension auto-detection). This
test is unit-level / fast: it does not load any model or run inference.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def _get_subparser(parser: argparse.ArgumentParser, name: str) -> argparse.ArgumentParser:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices[name]
    raise AssertionError(f"subparser {name!r} not found")


def _get_format_action(subparser: argparse.ArgumentParser) -> argparse.Action:
    for action in subparser._actions:
        if action.dest == "format":
            return action
    raise AssertionError("--format action not found")


def test_map_format_choices_include_sqlite():
    """`ontomap map --format sqlite ...` must parse without an argparse error."""
    from ontomap.cli import build_parser

    parser = build_parser()
    args = parser.parse_args([
        "map", "--text", "some free text", "--format", "sqlite", "--output", "/tmp/does_not_matter.sqlite",
    ])
    assert args.format == "sqlite"


def test_map_format_sqlite_matches_map_model_choices():
    """`map --format` sqlite choice should mirror `map-model --format`'s enum entry."""
    from ontomap.cli import build_parser

    parser = build_parser()
    map_format = _get_format_action(_get_subparser(parser, "map"))
    map_model_format = _get_format_action(_get_subparser(parser, "map-model"))
    assert "sqlite" in map_format.choices
    assert "sqlite" in map_model_format.choices


def test_write_results_explicit_format_sqlite(tmp_path: Path):
    """write_results(..., output_format="sqlite") — explicit format string, not via
    extension detection — must route to write_sqlite and produce a valid DB with a
    populated `predictions` table (mirrors tests/test_smoke.py::test_io_write_sqlite,
    but exercises the format-normalization dispatch path used by `map --format`)."""
    from ontomap import MapResult
    from ontomap.io import write_results

    r = MapResult(
        query_id="SSO:000000027",
        direction="sso",
        source_name="1,2-phenylacetyl-CoA epoxidase, subunit A",
        source_ec="1.14.13.149",
        predictions=[("rxn16679", 0.97), ("rxn00148", 0.41)],
        confidence_calibrated=[0.91, 0.32],
        reaction_meta={
            "rxn16679": {
                "name": "phenylacetyl-CoA:oxygen oxidoreductase",
                "ec_list": ["1.14.13.149"],
                "equation": "phenylacetyl-CoA + O2 + NADPH + H+ -> ... + NADP+ + H2O",
                "pathway": ["Phenylalanine metabolism"],
                "ec_match_level": 4,
            }
        },
        latency_ms=128.0,
    )

    # Note the extension is deliberately NOT .sqlite — proves dispatch is driven by
    # the explicit output_format="sqlite" argument, not extension auto-detection.
    out = tmp_path / "results.out"
    write_results([r], out, output_format="sqlite", direction="sso")

    conn = sqlite3.connect(str(out))
    try:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert {"queries", "predictions", "reactions"} <= tables
        preds = conn.execute("SELECT reaction_id FROM predictions ORDER BY rank").fetchall()
        assert preds == [("rxn16679",), ("rxn00148",)]
    finally:
        conn.close()
