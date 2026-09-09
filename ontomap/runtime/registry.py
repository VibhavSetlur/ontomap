"""Small explicit registry; plugins are local implementations, not entry points."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from .schema import MappingQuery, MappingResult, ValidationError

class Plugin(Protocol):
    name: str
    version: str
    def map(self, query: MappingQuery) -> MappingResult: ...

@dataclass(frozen=True)
class Bundle:
    method: str
    version: str
    plugin: Plugin
    def describe(self) -> dict:
        metadata = getattr(self.plugin, "metadata", {})
        return {"method": self.method, "version": self.version,
                "plugin": type(self.plugin).__module__ + "." + type(self.plugin).__name__,
                "implementation": type(self.plugin).__module__ + "." + type(self.plugin).__name__,
                **metadata}

class Registry:
    def __init__(self) -> None: self._bundles: dict[tuple[str, str], Bundle] = {}
    def register(self, plugin: Plugin) -> None:
        key = (plugin.name, plugin.version)
        if key in self._bundles: raise ValueError(f"duplicate plugin: {key[0]}@{key[1]}")
        self._bundles[key] = Bundle(*key, plugin)
    def resolve(self, method: str, version: str | None = None) -> Bundle:
        matches = [bundle for (name, ver), bundle in self._bundles.items() if name == method and (version is None or ver == version)]
        if version is None and len(matches) > 1:
            defaults = [bundle for bundle in matches if getattr(bundle.plugin, "metadata", {}).get("default") is True]
            if len(defaults) == 1:
                return defaults[0]
        if len(matches) != 1:
            qualifier = f"{method}@{version}" if version else method
            raise ValidationError("unknown_method_version", f"no unique registered method/version: {qualifier}", "method")
        return matches[0]
    def methods(self) -> list[dict]: return [bundle.describe() for _, bundle in sorted(self._bundles.items())]
