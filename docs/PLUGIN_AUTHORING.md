# Plugin authoring and versioning

Implement `name`, `version`, and `map(MappingQuery) -> MappingResult`; register it explicitly. A version is immutable:
promote a new artifact by adding a new directory/manifest and version, then selecting it explicitly. Roll back by selecting
the former version; never overwrite a manifest-described artifact.
