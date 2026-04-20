from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from repo_intel.worker.context import ScanContext

_LANGUAGE_BY_SUFFIX = {
    ".js": "javascript",
    ".py": "python",
    ".tf": "hcl",
    ".ts": "typescript",
}
_ENTRYPOINT_CANDIDATES = {
    "src/index.ts",
    "src/server.ts",
    "src/app.ts",
    "src/main.ts",
    "index.js",
    "server.js",
}
_IMPORTANT_FILENAMES = {
    "Dockerfile",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "requirements.txt",
    "pyproject.toml",
}


class FingerprintPhase:
    """Resolve immutable repository identity for the checked out ref."""

    def run(self, context: ScanContext) -> dict[str, Any]:
        if context.checkout_path is None:
            raise ValueError("checkout path is required before fingerprinting")
        if context.resolved_commit_sha is None:
            context.resolved_commit_sha = self._git_output("rev-parse", "HEAD", cwd=context.checkout_path)
        return build_fingerprint(context.checkout_path)

    def _git_output(self, *args: str, cwd: Path) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout.strip()


def build_fingerprint(root: Path) -> dict[str, Any]:
    files = [path for path in root.rglob("*") if path.is_file() and ".git" not in path.relative_to(root).parts]
    relative_paths = {path.relative_to(root).as_posix() for path in files}
    languages = sorted({_LANGUAGE_BY_SUFFIX[path.suffix.lower()] for path in files if path.suffix.lower() in _LANGUAGE_BY_SUFFIX})
    important_paths = sorted(
        path for path in relative_paths if Path(path).name in _IMPORTANT_FILENAMES or path.startswith(".github/workflows/")
    )
    package_managers = _detect_package_managers(relative_paths)
    framework_hints = _detect_framework_hints(root, relative_paths)
    entrypoints = sorted(path for path in relative_paths if path in _ENTRYPOINT_CANDIDATES)
    has_terraform = any(path.endswith(".tf") for path in relative_paths)

    return {
        "languages": languages,
        "package_managers": package_managers,
        "framework_hints": framework_hints,
        "important_paths": important_paths,
        "entrypoint_candidates": entrypoints,
        "has_docker": "Dockerfile" in relative_paths,
        "has_github_actions": any(path.startswith(".github/workflows/") for path in relative_paths),
        "has_terraform": has_terraform,
    }


def _detect_package_managers(paths: set[str]) -> list[str]:
    managers: set[str] = set()
    if "package.json" in paths or "package-lock.json" in paths:
        managers.add("npm")
    if "pnpm-lock.yaml" in paths:
        managers.add("pnpm")
    if "yarn.lock" in paths:
        managers.add("yarn")
    if "requirements.txt" in paths or "pyproject.toml" in paths:
        managers.add("pip")
    return sorted(managers)


def _detect_framework_hints(root: Path, paths: set[str]) -> list[str]:
    hints: set[str] = set()
    if "package.json" in paths:
        hints.update(_frameworks_from_package_json(root / "package.json"))
    if "requirements.txt" in paths:
        hints.update(_frameworks_from_text(root / "requirements.txt"))
    if "pyproject.toml" in paths:
        hints.update(_frameworks_from_text(root / "pyproject.toml"))
    return sorted(hints)


def _frameworks_from_package_json(path: Path) -> set[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return set()
    deps = {
        **payload.get("dependencies", {}),
        **payload.get("devDependencies", {}),
    }
    found: set[str] = set()
    if "express" in deps:
        found.add("express")
    if "fastify" in deps:
        found.add("fastify")
    if "@nestjs/core" in deps:
        found.add("nestjs")
    return found


def _frameworks_from_text(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8").lower()
    except (OSError, UnicodeDecodeError):
        return set()
    found: set[str] = set()
    for framework in ("flask", "fastapi", "django"):
        if framework in text:
            found.add(framework)
    return found
