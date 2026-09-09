"""Immutable local artifact manifest and checksum verification."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from .schema import ValidationError


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("invalid_manifest", f"cannot read manifest: {exc}", "manifest") from exc
    if manifest.get("schema_version") != 1 or not manifest.get("files"):
        raise ValidationError("invalid_manifest", "manifest requires schema_version 1 and files", "manifest")
    return manifest


def verify_manifest(path: Path) -> dict:
    manifest = load_manifest(path)
    for name, expected in manifest["files"].items():
        artifact = path.parent / name
        if not artifact.is_file():
            raise ValidationError("artifact_missing", f"artifact is missing: {name}", name)
        actual = sha256(artifact)
        if actual != expected["sha256"]:
            raise ValidationError("artifact_checksum_mismatch", f"checksum mismatch: {name}", name)
    return manifest
