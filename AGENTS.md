# AI agent guidance

Work within a project-local `.venv` and treat `ontomap --help`, tests, package metadata, manifests, and source as authoritative. Preserve public CLI/API behavior, all serializers, registry versions, artifact provenance, and ModelSEED acquire-only policy. Do not add credentials, private/Henry/Filipe data, or restricted ModelSEED records to the repository. Keep documentation user-facing and free of internal orchestration language.

Before changing code or docs, identify direct callers and relevant tests. After changes, run the narrowest real command plus the relevant tests; use the full suite for repository-wide work. New research artifacts must be new immutable versioned directories/manifests with checksum/benchmark metadata, tests, and documentation—never overwrite existing artifacts. Use explicit registry versions for comparison and rollback.
