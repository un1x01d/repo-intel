# repo-intel

`repo-intel` is a production-oriented MVP for repository intelligence.
This step bootstraps deterministic scan orchestration and data modeling first, with AI reasoning interfaces stubbed for later integration.

## What is included

- FastAPI application with:
  - `GET /health`
  - `POST /scans`
  - `GET /scans/{scan_id}`
- SQLAlchemy 2.x models and Alembic migration setup
- Repository and service layer abstractions
- Worker stubs for scan orchestration phases
- AI stubs for future Vertex-backed reasoning
- Pytest coverage for API, models, and service behavior

## Requirements

- Python 3.11+
- PostgreSQL
- `git` installed and available on `PATH`

## Environment variables

- `REPO_INTEL_DB_URL` (optional): SQLAlchemy DB URL, defaults to `postgresql+psycopg://postgres:postgres@localhost:5432/repo_intel`
- `REPO_INTEL_APP_ENV` (optional, default `dev`): runtime environment
- `REPO_INTEL_LOG_LEVEL` (optional, default `INFO`): logging level
- `REPO_INTEL_WORKER_CHECKOUT_ROOT` (optional, default `/tmp/repo-intel/checkouts`): worker checkout directory
- `REPO_INTEL_AI_ENABLED` (optional, default `false`): enables Vertex-backed reasoning after deterministic extraction
- `REPO_INTEL_VERTEX_PROJECT_ID` (required when AI is enabled): Google Cloud project for Vertex AI
- `REPO_INTEL_VERTEX_LOCATION` (optional, default `us-central1`): Vertex AI location
- `REPO_INTEL_VERTEX_MODEL` (optional, default `gemini-2.0-flash-001`): Gemini model name
- `REPO_INTEL_VERTEX_CONTEXT_CACHE_ENABLED` (optional, default `false`): placeholder toggle for future context caching

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## Run migrations

```bash
export REPO_INTEL_DB_URL='postgresql+psycopg://user:pass@localhost:5432/repo_intel'
alembic upgrade head
```

## Start the API

```bash
export REPO_INTEL_DB_URL='postgresql+psycopg://user:pass@localhost:5432/repo_intel'
uvicorn repo_intel.main:app --reload
```

## Create and run a scan

Create a queued scan:

```bash
curl -X POST http://localhost:8000/scans \
  -H 'content-type: application/json' \
  -d '{
    "repo_url": "https://github.com/org/repo",
    "ref": "main",
    "provider": "github",
    "auth_mode": "github_app",
    "options": {
      "enable_ai_summary": true,
      "enable_security": true,
      "enable_performance": true,
      "enable_git_analysis": true
    }
  }'
```

Run the scan synchronously through the local worker:

```bash
curl -X POST http://localhost:8000/scans/{scan_id}/run
```

Check status and available artifact types:

```bash
curl http://localhost:8000/scans/{scan_id}
```

Fetch stored artifacts:

```bash
curl http://localhost:8000/scans/{scan_id}/artifacts
```

This step produces:

- `fingerprint`: languages, package managers, framework hints, important paths, entrypoint candidates, Docker, GitHub Actions, and Terraform presence.
- `inventory_summary`: aggregate file counts, config/source/infra/binary counts, and language counts.
- `structure_summary`: JavaScript and TypeScript source file, symbol, import, and route counts.
- `route_summary`: detected Express/Fastify route counts by framework and HTTP method.
- `dependency_summary`: npm dependency counts by dependency type.
- `integration_summary`: first-pass service integration counts by type and provider.
- `git_summary`: bounded recent commit history, hot files, critical file churn, and author concentration signals.
- `hotspot_summary`: deterministic hotspot-style file signals derived from git churn.
- `finding_summary`: normalized finding counts by category.

## Deterministic extraction

The worker now performs heuristic-first extraction for Node.js, JavaScript, and TypeScript repositories:

- Symbols: `function`, `class`, `const`, `interface`, `type`, and `enum` declarations.
- Imports: ES module imports and CommonJS `require(...)` calls, with local `./` and `../` resolution for `.ts`, `.tsx`, `.js`, `.jsx`, and index files.
- Routes: first-pass Express router/app patterns and Fastify method calls.
- Dependencies: `package.json` dependencies, dev dependencies, peer dependencies, optional dependencies, and package-lock versions where available.
- Integrations: first-pass Node.js/TypeScript usage of HTTP clients, databases, caches, queues, storage SDKs, and auth libraries.
- Git intelligence: recent commits, per-file churn, critical-file changes, hot files, and simple author concentration metrics.
- Findings: deterministic architecture, change-risk, dependency, and performance-risk signals linked to evidence records.

Example detected route:

```json
{
  "framework": "express",
  "method": "GET",
  "path": "/health",
  "handler_name": "healthHandler"
}
```

Example dependency artifact:

```json
{
  "ecosystem": "npm",
  "prod_dependencies": 34,
  "dev_dependencies": 12,
  "peer_dependencies": 1,
  "optional_dependencies": 0
}
```

Example integration artifact:

```json
{
  "integration_counts": {
    "http_api": 2,
    "database": 1,
    "cache": 1
  },
  "providers": {
    "axios": 1,
    "fetch": 1,
    "postgresql": 1,
    "redis": 1
  }
}
```

Example git hotspot artifact:

```json
{
  "hotspots": [
    {
      "kind": "high_churn_critical_file",
      "path": "src/middleware/auth.ts",
      "score": 1.0
    }
  ]
}
```

Fetch graph and findings:

```bash
curl http://localhost:8000/scans/{scan_id}/graph
curl http://localhost:8000/scans/{scan_id}/findings
curl 'http://localhost:8000/scans/{scan_id}/findings?category=change-risk&severity=high'
```

## Vertex-backed reasoning

The AI layer is optional and runs after deterministic extraction. Deterministic facts remain the source of truth; Vertex receives bounded context packs assembled from stored artifacts, findings, graph counts, routes, integrations, dependencies, and selected evidence. The worker does not dump the whole repository into prompts.

Enable AI locally with standard Google ADC credentials:

```bash
export REPO_INTEL_AI_ENABLED=true
export REPO_INTEL_VERTEX_PROJECT_ID='your-gcp-project'
export REPO_INTEL_VERTEX_LOCATION='us-central1'
export REPO_INTEL_VERTEX_MODEL='gemini-2.0-flash-001'
```

When enabled, completed scans can produce:

- `ai_summary_context`: bounded context used for summary generation.
- `ai_hotspot_context`: bounded context used for hotspot reasoning.
- `ai_ask_context`: latest bounded context used for Q&A.
- `ai_error`: controlled failure details if AI generation fails after deterministic extraction.
- `ai_insights` rows of type `summary`, `hotspot`, and `qa`.

Fetch generated AI outputs:

```bash
curl http://localhost:8000/scans/{scan_id}/summary
curl http://localhost:8000/scans/{scan_id}/insights
curl -X POST http://localhost:8000/scans/{scan_id}/ask \
  -H 'content-type: application/json' \
  -d '{"question": "What does Redis affect in this repository?"}'
```

AI output is validated as structured JSON before persistence. Stored AI insights must cite evidence IDs from the context pack and are linked through `insight_evidence_links`.

Current limitations:

- Extraction is deterministic and regex/token heuristic based; it is not a full AST parser.
- Method extraction and call graph extraction are intentionally limited.
- Terraform parsing is not implemented yet.
- Route extraction focuses on straightforward single-line Express and Fastify patterns.
- Integration detection is usage-signal based. It does not prove runtime connectivity or configuration correctness.
- Git extraction is bounded to recent history and degrades to empty metrics if git history commands are unavailable.
- Findings are conservative risk signals and concentrations, not confirmed vulnerabilities or performance defects.
- Vertex reasoning is grounded in selected stored facts and evidence. It may summarize or contextualize risk signals, but it is not authoritative without the cited evidence.
- `/ask` uses deterministic keyword retrieval over stored facts. There is no vector database or full-repo semantic retrieval yet.

## Run tests

```bash
pytest
```
