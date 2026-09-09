"""Offline contract tests for pinned ModelSEED acquisition."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ontomap import modelmap


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "build_corpus.py"
PIN = "194ac8afe48f8a606c0dd07ba3c7af10c02ba2fd"


def test_modelseed_dry_run_is_pinned_and_network_free():
    result = subprocess.run(
        [".venv/bin/python", str(SCRIPT), "--dry-run"], cwd=ROOT,
        check=True, capture_output=True, text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["commit"] == PIN
    assert payload["external_records_only"] is True
    assert all(f"/{PIN}/" in url for url in payload["files"].values())
    assert payload["license_url"].endswith("/ModelSEEDDatabase/master/LICENSE")


def test_modelseed_requires_explicit_external_source(monkeypatch):
    monkeypatch.delenv("ONTOMAP_MODELSEED", raising=False)
    with pytest.raises(FileNotFoundError, match="not configured"):
        modelmap._resolve_modelseed_dir()


def test_modelseed_explicit_source_is_selected(tmp_path):
    assert modelmap._resolve_modelseed_dir(tmp_path) == tmp_path
