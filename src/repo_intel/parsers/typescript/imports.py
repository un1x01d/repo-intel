from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ParsedImport:
    imported_path: str
    import_kind: str
    line_start: int


_IMPORT_FROM_RE = re.compile(r"""^\s*import\s+.+?\s+from\s+["']([^"']+)["']""")
_SIDE_EFFECT_RE = re.compile(r"""^\s*import\s+["']([^"']+)["']""")
_REQUIRE_ASSIGN_RE = re.compile(r"""^\s*(?:const|let|var)\s+.+?\s*=\s*require\(["']([^"']+)["']\)""")
_REQUIRE_RE = re.compile(r"""require\(["']([^"']+)["']\)""")


def parse_imports(source: str) -> list[ParsedImport]:
    imports: list[ParsedImport] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        if line.lstrip().startswith("//"):
            continue
        match = _IMPORT_FROM_RE.search(line)
        if match:
            imports.append(ParsedImport(match.group(1), "import", line_number))
            continue
        match = _SIDE_EFFECT_RE.search(line)
        if match:
            imports.append(ParsedImport(match.group(1), "side_effect_import", line_number))
            continue
        match = _REQUIRE_ASSIGN_RE.search(line)
        if match:
            imports.append(ParsedImport(match.group(1), "require", line_number))
            continue
        for match in _REQUIRE_RE.finditer(line):
            imports.append(ParsedImport(match.group(1), "require", line_number))
    return imports


def resolve_local_import(source_file: Path, imported_path: str, repo_root: Path) -> str | None:
    if not imported_path.startswith(("./", "../")):
        return None
    base = (source_file.parent / imported_path).resolve()
    root = repo_root.resolve()
    candidates = [base]
    candidates.extend(base.with_suffix(suffix) for suffix in (".ts", ".tsx", ".js", ".jsx"))
    candidates.extend(base / f"index{suffix}" for suffix in (".ts", ".tsx", ".js", ".jsx"))
    for candidate in candidates:
        if candidate.is_file() and candidate.resolve().is_relative_to(root):
            return candidate.resolve().relative_to(root).as_posix()
    return None
