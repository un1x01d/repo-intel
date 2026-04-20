from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ParsedDependency:
    package_name: str
    version_spec: str | None
    locked_version: str | None
    dependency_type: str
    ecosystem: str = "npm"


_PACKAGE_SECTIONS = {
    "dependencies": "prod",
    "devDependencies": "dev",
    "peerDependencies": "peer",
    "optionalDependencies": "optional",
}


def parse_package_json(path: Path) -> list[ParsedDependency]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    dependencies: list[ParsedDependency] = []
    for section, dependency_type in _PACKAGE_SECTIONS.items():
        values = payload.get(section, {})
        if not isinstance(values, dict):
            continue
        for package_name, version_spec in sorted(values.items()):
            dependencies.append(
                ParsedDependency(
                    package_name=package_name,
                    version_spec=str(version_spec),
                    locked_version=None,
                    dependency_type=dependency_type,
                )
            )
    return dependencies


def apply_package_lock(dependencies: list[ParsedDependency], lock_path: Path) -> list[ParsedDependency]:
    if not lock_path.exists():
        return dependencies
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return dependencies
    locked_versions = _locked_versions(payload)
    return [
        ParsedDependency(
            package_name=dependency.package_name,
            version_spec=dependency.version_spec,
            locked_version=locked_versions.get(dependency.package_name),
            dependency_type=dependency.dependency_type,
            ecosystem=dependency.ecosystem,
        )
        for dependency in dependencies
    ]


def _locked_versions(payload: dict[str, Any]) -> dict[str, str]:
    versions: dict[str, str] = {}
    packages = payload.get("packages")
    if isinstance(packages, dict):
        for key, value in packages.items():
            if not key.startswith("node_modules/") or not isinstance(value, dict):
                continue
            version = value.get("version")
            if isinstance(version, str):
                versions[key.removeprefix("node_modules/")] = version
    dependencies = payload.get("dependencies")
    if isinstance(dependencies, dict):
        for package_name, value in dependencies.items():
            if isinstance(value, dict) and isinstance(value.get("version"), str):
                versions.setdefault(package_name, value["version"])
    return versions
