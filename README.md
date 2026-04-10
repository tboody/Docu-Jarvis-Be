# Docu-Jarvis Backend

FastAPI backend that wraps the `docu-jarvis` Go CLI binary and exposes it as a REST + SSE API.

## Setup

```bash
# 1. Install dependencies
poetry install

# 2. Copy and configure environment
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY and verify DOCU_JARVIS_BINARY path

# 3. Start
poetry run uvicorn app.main:app --reload --port 8000
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/analyze` | Submit analysis job (returns `job_id` immediately) |
| `GET` | `/api/v1/jobs/{id}` | Poll job status + result |
| `GET` | `/api/v1/jobs/{id}/stream` | SSE stream of real-time progress |
| `DELETE` | `/api/v1/jobs/{id}` | Clean up temp files |
| `GET` | `/health` | Binary path + health check |

## Modes

| Mode | Description |
|------|-------------|
| `security` | OWASP Top 10 scan with AST + data-flow analysis |
| `impact` | Change blast-radius via BFS call graph (risk 0–100) |
| `why` | Git-history archaeology — why does this code exist? |
| `debug` | Find which commit introduced a bug (date range) |
| `explain` | Interactive commit conversation |

## Interactive API docs

`http://localhost:8000/docs`
