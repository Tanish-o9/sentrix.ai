# SENTRIX.ai Architecture & System Design

SENTRIX.ai is an Autonomous Software Engineering platform that bridges **Agno Multi-Agent Intelligence** with **Django Trusted Execution Guardrails**.

## System Overview

```mermaid
flowchart TD
    User["Developer / Human Reviewer"]
    UI["Dashboard UI & In-Browser Editor"]
    API["Django REST API Layer"]
    DB[("SQLite / PostgreSQL State Store")]
    WS["Isolated Workspaces Engine"]
    
    subgraph AgnoAgents ["Agno Multi-Agent Pipeline"]
        Planner["Project Manager & Analyst"]
        Dev["Developer Agent (Code Synthesizer)"]
        QA["QA Verification Agent"]
        Debug["Debugger Agent (Self-Healing Loop)"]
        Review["Security & Audit Reviewer"]
    end
    
    subgraph GitEngine ["Git & GitHub Gateway"]
        LocalGit["Git Branch & Worktree Manager"]
        PatchGen["SHA-256 Cryptographic Lock"]
        GitHub["GitHub API (PR / Fork Assistant)"]
    end

    User -->|Prompts / Web Edits| UI
    UI -->|REST Endpoints| API
    API --> DB
    API --> WS
    WS --> AgnoAgents
    AgnoAgents --> PatchGen
    PatchGen -->|Requires Human Approval| User
    User -->|Approve Signature| API
    API --> GitEngine
    GitEngine --> GitHub
```

## Architectural Boundaries

1. **Guarded Autonomy:** AI agents never have direct permission to push code to remote branches or production without human signature.
2. **Cryptographic Patch Lock:** Every generated unified diff is hashed with SHA-256 (`calculate_patch_hash`). Any modification requires re-hashing and explicit re-approval.
3. **Bounded Repair Loop:** If tests fail in the sandbox, the Debugger and Developer agents collaborate in a bounded 3-cycle repair loop before surfacing the patch.
