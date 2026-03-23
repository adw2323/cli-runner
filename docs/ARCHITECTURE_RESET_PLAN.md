# Architecture Reset Plan (Codex-Only)

## Goal
Align implementation with a Codex-only controller architecture.

## Remediation Steps
1. Remove non-Codex agent/session model constructs.
2. Remove plan/delegation parsing and broker orchestration surfaces.
3. Simplify UI to Codex-only controls and Codex/Broker logs.
4. Remove non-Codex tests and add Codex-only assertions.
5. Update docs/metadata to codex-only positioning.
6. Re-run full tests with coverage gate.

## Completion Criteria
- no Claude/Gemini/delegation plan execution path in app code,
- broker manages only Codex session lifecycle,
- UI exposes only Codex session controls/visibility,
- test suite passes coverage threshold.
