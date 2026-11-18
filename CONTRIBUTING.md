# Contributing to SENTRIX.ai

Thank you for contributing to SENTRIX.ai!

## Development Guidelines

1. **Guarded Autonomy:** All agent-generated code must produce a valid unified diff with SHA-256 hash validation before deployment.
2. **Minimal Complexity:** Write simple, maintainable, readable code with zero unnecessary abstractions.
3. **Tests Required:** Any new endpoint or agent capability must include automated unit tests in `tests/test_sentrix.py`.
4. **Clean Commits:** Follow conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `ci:`).
