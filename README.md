# SENTRIX.ai — Autonomous AI Software Engineering Platform

Lightweight, clean, production-grade implementation of **SENTRIX.ai** built with **Django** (backend, DB, and guardrails) and **Agno** (multi-agent orchestration).

---

## 🎯 Architecture & Separation of Concerns

```
SENTRIX.ai/
├── sentrix_agno/              # 🧠 100% AGNO (AI Multi-Agent Intelligence)
│   ├── schemas.py             # Pydantic structured output models (TaskPlan, PatchProposal, ReviewReport)
│   └── workflow.py            # Agno Agents (PM, Developer, Debugger, Reviewer) and Execution Pipeline
│
├── sentrix_backend/           # 🛡️ 100% DJANGO (Backend, Database, Execution Guardrails)
│   ├── models.py              # Authoritative state: Project, Task, TaskStep, CodePatch, Approval
│   ├── services.py            # Security boundary: Git workspace cloning, AST scanning, SHA-256 patch hashing, GitHub API
│   ├── views.py               # REST API endpoints + Visual Human Approval Dashboard
│   ├── urls.py                # App URL routing
│   ├── urls_root.py           # Root URL routing (/api/)
│   └── settings.py            # Minimal Django configuration
│
├── tests/
│   └── test_sentrix.py        # End-to-end integration tests (Django + Agno pipeline)
├── manage.py                  # Django CLI entrypoint
└── requirements.txt
```

---

## 🔍 Who Does What?

| Responsibility | Handled By | Why |
| :--- | :--- | :--- |
| **Task Planning & Specs** | `sentrix_agno` (Agno Planner) | Agno agent decomposes user intent into measurable criteria |
| **Patch Generation (Diff)** | `sentrix_agno` (Agno Developer) | Generates minimal git unified diff (cannot touch filesystem directly) |
| **Bounded Self-Healing QA** | `sentrix_agno` (Agno Debugger) | Diagnoses test failures in sandbox and repairs patch (max 3 retries) |
| **Security & Quality Audit** | `sentrix_agno` (Agno Reviewer) | Checks patch against risks, secrets, and test plan |
| **Workspace & Git Cloning** | `sentrix_backend` (Django Services) | Safely clones GitHub repos into controlled directories |
| **AST Codebase Scanner** | `sentrix_backend` (Django Services) | Extracts functions and classes via Python `ast` module |
| **Cryptographic Patch Hash** | `sentrix_backend` (Django Services) | Computes SHA-256 hash to lock approval to exact bytes |
| **Human Approval Enforcement** | `sentrix_backend` (Django Views) | Prevents applying patch or creating PR without valid approval |
| **GitHub Draft PR Creation** | `sentrix_backend` (Django Services) | Generates branch & Draft PR upon human approval |

---

## 🚀 Quickstart

### 1. Run Migrations
```bash
python manage.py migrate
```

### 2. Run Tests
```bash
python manage.py test tests
```

### 3. Start Server
```bash
python manage.py runserver 127.0.0.1:8000
```
Then visit: `http://127.0.0.1:8000/`
