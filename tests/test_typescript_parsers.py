from __future__ import annotations

from pathlib import Path

from repo_intel.parsers.typescript.dependencies import apply_package_lock, parse_package_json
from repo_intel.parsers.typescript.imports import parse_imports, resolve_local_import
from repo_intel.parsers.typescript.integrations import parse_integrations
from repo_intel.parsers.typescript.routes import parse_routes
from repo_intel.parsers.typescript.symbols import parse_symbols


def test_symbol_parser_detects_supported_declarations() -> None:
    source = """
export function login() {}
function helper() {}
export class UserService {}
const foo = () => {}
export const bar = async () => {}
export interface User {}
export type UserId = string;
export enum Role {}
"""
    symbols = parse_symbols(source)

    assert [(symbol.name, symbol.kind, symbol.exported) for symbol in symbols] == [
        ("login", "function", True),
        ("helper", "function", False),
        ("UserService", "class", True),
        ("foo", "const", False),
        ("bar", "const", True),
        ("User", "interface", True),
        ("UserId", "type", True),
        ("Role", "enum", True),
    ]


def test_import_parser_detects_import_and_require_forms() -> None:
    source = """
import express from "express";
import { login } from "./auth";
import * as fs from "fs";
const config = require("../config");
let logger = require("./logger");
// require("ignored");
require("dotenv").config();
"""
    imports = parse_imports(source)

    assert [item.imported_path for item in imports] == ["express", "./auth", "fs", "../config", "./logger", "dotenv"]


def test_local_import_resolver_supports_extension_and_index(tmp_path: Path) -> None:
    (tmp_path / "src" / "routes").mkdir(parents=True)
    (tmp_path / "src" / "services").mkdir()
    source_file = tmp_path / "src" / "routes" / "auth.ts"
    source_file.write_text("import x from '../services/auth';", encoding="utf-8")
    (tmp_path / "src" / "services" / "auth.ts").write_text("export const x = 1;", encoding="utf-8")

    assert resolve_local_import(source_file, "../services/auth", tmp_path) == "src/services/auth.ts"


def test_route_parser_detects_express_and_fastify_routes() -> None:
    source = """
app.get("/health", healthHandler)
router.post("/login", authController.login)
fastify.get("/users", async function usersHandler() {})
app.get("/ready", readyHandler); router.delete("/sessions/:id", destroySession)
"""
    routes = parse_routes(source)

    assert [(route.framework, route.method, route.path, route.handler_name) for route in routes] == [
        ("express", "GET", "/health", "healthHandler"),
        ("express", "POST", "/login", "authController.login"),
        ("fastify", "GET", "/users", None),
        ("express", "GET", "/ready", "readyHandler"),
        ("express", "DELETE", "/sessions/:id", "destroySession"),
    ]


def test_dependency_parser_reads_package_json_and_lock(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"express":"^4.0.0"},"devDependencies":{"typescript":"^5.0.0"}}',
        encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text(
        '{"packages":{"node_modules/express":{"version":"4.18.0"}}}',
        encoding="utf-8",
    )

    dependencies = apply_package_lock(parse_package_json(tmp_path / "package.json"), tmp_path / "package-lock.json")

    assert [(dep.package_name, dep.dependency_type, dep.locked_version) for dep in dependencies] == [
        ("express", "prod", "4.18.0"),
        ("typescript", "dev", None),
    ]


def test_integration_parser_detects_first_pass_service_usage() -> None:
    source = """
import axios from "axios";
import { Pool } from "pg";
const Redis = require("ioredis");
const jwt = require("jsonwebtoken");
fetch("https://example.com");
new Pool();
"""
    integrations = parse_integrations(source)

    assert [(item.integration_type, item.provider) for item in integrations] == [
        ("http_api", "axios"),
        ("database", "postgresql"),
        ("cache", "redis"),
        ("auth", "jsonwebtoken"),
        ("http_api", "fetch"),
        ("database", "postgresql"),
    ]
