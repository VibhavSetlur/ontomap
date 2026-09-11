# Architecture

`ontomap.runtime` provides validated queries/results, checksum verification, and a local explicit registry.
`ontomap.plugins` contains bundled implementations. `reaction@legacy-1` adapts the existing `Pipeline`; `go-text@4.0.0` is the checked-in corrected default. Its immutable artifact uses `go-height-lte-1-v1`: height is distance to the furthest descendant, `height <= 1` was applied before training and deduplicated splitting, and runtime never filters candidates. The training vocabulary is therefore the filtered vocabulary. `go-text@2.0.0` (prior depth model) and `go-text@3.0.0` (prior inverted-height model) remain explicit rollback choices. The registry has no discovery framework or network behavior.

`Registry.methods()` reports independently versioned plugin/method and implementation identity plus schema,
artifact/checksum, benchmark/metric schema, compatibility/deprecation, provenance, and runtime metadata where a plugin supplies it.
Methods are explicitly selected by `method` and immutable `version`; add a new plugin/artifact version to promote it and select a
former version to roll back. Existing `Pipeline` and `reaction@legacy-1` remain one-release deprecated adapters.
