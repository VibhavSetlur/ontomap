# Architecture

`ontomap.runtime` provides validated queries/results, checksum verification, and a local explicit registry.
`ontomap.plugins` contains bundled implementations. `reaction@legacy-1` adapts the existing `Pipeline`; `go-text@1.0.0`
loads only the checked-in Filipe artifact. The registry has no discovery framework or network behavior.

`Registry.methods()` reports independently versioned plugin/method and implementation identity plus schema,
artifact/checksum, benchmark/metric schema, compatibility/deprecation, provenance, and runtime metadata where a plugin supplies it.
Methods are explicitly selected by `method` and immutable `version`; add a new plugin/artifact version to promote it and select a
former version to roll back. Existing `Pipeline` and `reaction@legacy-1` remain one-release deprecated adapters.
