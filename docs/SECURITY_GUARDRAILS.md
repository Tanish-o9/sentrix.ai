# SENTRIX.ai Security Guardrails

SENTRIX enforces strict security barriers across the software lifecycle:

1. **Path Traversal Protection:** All file reads and writes are validated with real filesystem boundaries (`startswith(ws_resolved)`).
2. **Subprocess Isolation:** Test execution blocks prohibited system commands (`rm -rf`, raw sockets, etc.) and isolates environment variables to prevent secret leaks.
3. **Cryptographic Gate:** Unified diffs are locked with SHA-256 signatures before human reviewers sign off on them.
4. **Non-Interactive Git:** All git processes execute with `GIT_TERMINAL_PROMPT=0` to prevent CLI deadlocks.
