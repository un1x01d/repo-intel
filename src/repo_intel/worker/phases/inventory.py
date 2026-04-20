from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from repo_intel.storage.models import RepoFile
from repo_intel.storage.repositories import RepoFileStore
from repo_intel.worker.context import ScanContext

_SKIPPED_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv"}
_CONFIG_NAMES = {
    ".env",
    ".env.example",
    "alembic.ini",
    "dockerfile",
    "makefile",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.cfg",
    "tox.ini",
}
_ENTRYPOINT_NAMES = {"main.py", "app.py", "server.py", "manage.py"}
_LANGUAGE_BY_SUFFIX = {
    ".go": "go",
    ".hcl": "hcl",
    ".js": "javascript",
    ".jsx": "javascript",
    ".py": "python",
    ".rs": "rust",
    ".tf": "hcl",
    ".ts": "typescript",
    ".tsx": "typescript",
}
_SOURCE_SUFFIXES = set(_LANGUAGE_BY_SUFFIX)
_INFRA_SUFFIXES = {".tf", ".hcl"}
_MAX_HASH_BYTES = 20 * 1024 * 1024
_BINARY_SAMPLE_BYTES = 8192


class FileClassifier:
    """Explicit, testable file classification heuristics."""

    def classify(self, root: Path, path: Path) -> dict[str, Any]:
        relative_path = path.relative_to(root).as_posix()
        sample = read_sample(path)
        binary = is_binary(sample)
        size = path.stat().st_size
        return {
            "path": relative_path,
            "file_type": "binary" if binary else "text",
            "language": language_for_path(path),
            "size_bytes": size,
            "sha256": hash_file(path) if size <= _MAX_HASH_BYTES else None,
            "is_generated": is_generated_path(relative_path),
            "is_config": is_config_path(relative_path),
            "is_entrypoint": is_entrypoint_path(relative_path),
        }


def language_for_path(path: Path) -> str | None:
    return _LANGUAGE_BY_SUFFIX.get(path.suffix.lower())


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_sample(path: Path, size: int = _BINARY_SAMPLE_BYTES) -> bytes:
    with path.open("rb") as handle:
        return handle.read(size)


def is_binary(data: bytes) -> bool:
    if b"\x00" in data:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def is_generated_path(path: str) -> bool:
    lowered = path.lower()
    return (
        lowered.endswith((".lock", ".min.js", ".generated.py"))
        or "/dist/" in f"/{lowered}"
        or "/build/" in f"/{lowered}"
        or lowered.startswith("generated/")
    )


def is_config_path(path: str) -> bool:
    name = Path(path).name.lower()
    suffix = Path(path).suffix.lower()
    return name in _CONFIG_NAMES or suffix in {".ini", ".toml", ".yaml", ".yml", ".json"}


def is_entrypoint_path(path: str) -> bool:
    normalized = path.lower()
    name = Path(normalized).name
    return name in _ENTRYPOINT_NAMES or normalized in {
        "src/index.ts",
        "src/server.ts",
        "src/app.ts",
        "src/main.ts",
        "index.js",
        "server.js",
    }


class InventoryPhase:
    """Persist a deterministic file inventory for the checked out repository."""

    def __init__(self, session: Session, classifier: FileClassifier | None = None) -> None:
        self.session = session
        self.classifier = classifier or FileClassifier()

    def run(self, context: ScanContext) -> dict[str, Any]:
        if context.checkout_path is None:
            raise ValueError("checkout path is required before inventory extraction")

        files = [self._repo_file(context, path) for path in self._iter_files(context.checkout_path)]
        RepoFileStore(self.session).replace_for_scan(context.scan_id, files)
        self.session.commit()
        return build_inventory_summary(files)

    def _iter_files(self, root: Path) -> list[Path]:
        paths: list[Path] = []
        for path in root.rglob("*"):
            if any(part in _SKIPPED_DIRS for part in path.relative_to(root).parts):
                continue
            if path.is_file():
                paths.append(path)
        return sorted(paths, key=lambda item: item.relative_to(root).as_posix())

    def _repo_file(self, context: ScanContext, path: Path) -> RepoFile:
        assert context.checkout_path is not None
        classified = self.classifier.classify(context.checkout_path, path)
        return RepoFile(scan_job_id=context.scan_id, **classified)


def build_inventory_summary(files: list[RepoFile]) -> dict[str, Any]:
    languages = Counter(file.language for file in files if file.language)
    return {
        "total_files": len(files),
        "source_files": sum(1 for file in files if file.language is not None),
        "config_files": sum(1 for file in files if file.is_config),
        "infra_files": sum(1 for file in files if Path(file.path).suffix.lower() in _INFRA_SUFFIXES),
        "binary_files": sum(1 for file in files if file.file_type == "binary"),
        "languages": dict(sorted(languages.items())),
    }
