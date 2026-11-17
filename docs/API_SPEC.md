# SENTRIX.ai REST API Specification

Complete reference for all HTTP endpoints exposed by the SENTRIX backend.

## Endpoints

### 1. Repository Intelligence
- `GET /api/ast/?repo_url=<url>`
  - Returns non-executable AST symbol summaries (functions, classes, file statistics).
- `GET /api/repo/tree/?repo_url=<url>`
  - Returns file hierarchy, folder structures, sizes, and file extensions.
- `GET /api/repo/file/?repo_url=<url>&path=<rel_path>`
  - Safely reads file text content with path-traversal prevention.
- `POST /api/repo/file/`
  - Saves file edits in local workspace.
- `POST /api/repo/commit-pr/`
  - Directly commits web code edits to a branch and creates a GitHub PR.

### 2. Task Lifecycle
- `GET /api/tasks/` — List all engineering tasks.
- `POST /api/tasks/` — Dispatch new task (`repo_url`, `prompt`).
- `GET /api/tasks/<id>/` — Inspect task details, plan, steps, and patch.
- `POST /api/tasks/<id>/run/` — Execute multi-agent loop (synchronous or `?async=1`).
- `POST /api/tasks/<id>/approve/` — Enforce cryptographic SHA-256 signature and deploy.
- `POST /api/tasks/<id>/update-diff/` — Edit unified diff inline and re-hash.
- `GET /api/tasks/<id>/download-patch/` — Download `.patch` attachment.

### 3. Settings & Webhooks
- `POST /api/settings/api-key/` — Save Gemini/OpenAI/Groq keys & GitHub PAT.
- `GET /api/settings/api-status/` — Verify active provider & GitHub integration.
- `POST /api/webhooks/github/` — Autonomous bot listening for `@sentrix` issue comments.
