from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from repo_intel.parsers.typescript.imports import parse_imports, resolve_local_import
from repo_intel.parsers.typescript.routes import parse_routes
from repo_intel.parsers.typescript.symbols import parse_symbols
from repo_intel.storage.models import FileImport, RepoFile, Route, Symbol
from repo_intel.storage.repositories import RepoFileStore, StructureStore
from repo_intel.worker.context import ScanContext

_SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx"}
_MAX_SOURCE_BYTES = 2 * 1024 * 1024


@dataclass(slots=True)
class ExtractStructurePhase:
    session: Session

    def run(self, context: ScanContext) -> dict[str, Any]:
        if context.checkout_path is None:
            raise ValueError("checkout path is required before structure extraction")

        files_by_path = RepoFileStore(self.session).map_by_path(context.scan_id)
        source_files = [file for file in files_by_path.values() if _should_extract_source(file)]
        symbols: list[Symbol] = []
        imports: list[FileImport] = []
        routes: list[Route] = []

        processed_files = 0
        for repo_file in source_files:
            source_path = context.checkout_path / repo_file.path
            try:
                source = source_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue

            processed_files += 1
            symbols.extend(_symbols_for_file(context, repo_file, source))
            imports.extend(_imports_for_file(context, repo_file, source, source_path, files_by_path, context.checkout_path))
            routes.extend(_routes_for_file(context, repo_file, source))

        store = StructureStore(self.session)
        store.replace_symbols(context.scan_id, symbols)
        store.replace_imports(context.scan_id, imports)
        store.replace_routes(context.scan_id, routes)
        self.session.commit()

        return {
            "source_files_processed": processed_files,
            "symbols_created": len(symbols),
            "imports_created": len(imports),
            "routes_detected": len(routes),
        }


def _should_extract_source(repo_file: RepoFile) -> bool:
    if Path(repo_file.path).suffix.lower() not in _SOURCE_SUFFIXES:
        return False
    if repo_file.file_type == "binary" or repo_file.is_generated:
        return False
    return repo_file.size_bytes is None or repo_file.size_bytes <= _MAX_SOURCE_BYTES


def _symbols_for_file(context: ScanContext, repo_file: RepoFile, source: str) -> list[Symbol]:
    return [
        Symbol(
            scan_job_id=context.scan_id,
            file_id=repo_file.id,
            symbol_name=symbol.name,
            symbol_kind=symbol.kind,
            line_start=symbol.line_start,
            line_end=symbol.line_end,
            exported=symbol.exported,
        )
        for symbol in parse_symbols(source)
    ]


def _imports_for_file(
    context: ScanContext,
    repo_file: RepoFile,
    source: str,
    source_path: Path,
    files_by_path: dict[str, RepoFile],
    repo_root: Path,
) -> list[FileImport]:
    imports: list[FileImport] = []
    for parsed_import in parse_imports(source):
        resolved_path = resolve_local_import(source_path, parsed_import.imported_path, repo_root)
        imports.append(
            FileImport(
                scan_job_id=context.scan_id,
                source_file_id=repo_file.id,
                imported_path=parsed_import.imported_path,
                resolved_file_id=files_by_path[resolved_path].id if resolved_path in files_by_path else None,
                import_kind=parsed_import.import_kind,
            )
        )
    return imports


def _routes_for_file(context: ScanContext, repo_file: RepoFile, source: str) -> list[Route]:
    return [
        Route(
            scan_job_id=context.scan_id,
            file_id=repo_file.id,
            framework=route.framework,
            method=route.method,
            path=route.path,
            handler_name=route.handler_name,
            line_start=route.line_start,
        )
        for route in parse_routes(source)
    ]
