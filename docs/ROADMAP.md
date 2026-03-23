# cli-runner Roadmap

## Recommendation Summary
- Build v1 as a Windows-first, single-agent CLI runner with explicit adapter support for `codex`, `gemini`, and `claude`.
- Keep output handling stable: plain pipe streaming by default, no PTY dependency, no color formatting requirements.
- Publish as a Python package on PyPI with MIT license and a simple install path.
- Keep multi-agent orchestration out of v1 and track it as post-v1 roadmap work.

## Scope Guardrails
- In scope for v1:
  - `cli-runner --agent <codex|gemini|claude> "<prompt>"`
  - Deterministic loop control with machine-readable run status.
  - Windows-first compatibility and tests.
  - Install, doctor checks, and clear failure messages.
- Out of scope for v1:
  - PTY-first rendering and rich color UX.
  - Multi-agent choreography.
  - Desktop GUI.

## Milestones
| Milestone | Goal | Key Deliverables | Exit Criteria |
|---|---|---|---|
| M0 (baseline) | Stabilize current core | Existing loop runner, strict completion gate, status parsing, 90%+ coverage | Current tests remain green after refactor prep |
| M1 | Multi-agent adapter architecture | `--agent` flag, adapter interface, `codex/gemini/claude` adapters, command detection, actionable install/auth errors | `cli-runner --agent X` works for all 3 agents in integration tests |
| M2 | Packaging and quality hardening | CI on Windows, PyPI-ready metadata, `doctor` command, release docs | Clean CI on Windows, build artifacts pass package checks |
| M3 | Public v1 release | GitHub release + PyPI publish + versioned changelog | `pip install cli-runner` works on clean Windows environment |
| M4 (post-v1) | Multi-agent roadmap | Sequential/parallel strategy doc, prototype command surface | Approved design and prototype spike |

## v1 Architecture Decisions
- Adapter contract:
  - `build_cmd(prompt, extra_args) -> list[str]`
  - `detect() -> readiness result with install/auth hints`
- Runner core remains agent-agnostic:
  - Loop control, status parsing, strict completion, retry/continue logic.
- Status protocol:
  - Retain explicit `RUN_STATUS:DONE|CONTINUE|REWORK`.
  - Parse standalone status lines only.
- Process model:
  - Use `subprocess` with pipes and streamed line output.
  - Default environment disables ANSI/color noise where possible.
- Error model:
  - Missing binary or auth: fail fast with actionable guidance.
  - Loop cap reached: deterministic non-success exit.

## Test Strategy
- Unit tests:
  - Adapter command construction and readiness detection.
  - Status extraction and strict completion checks.
  - Windows command resolution behavior.
- Integration tests:
  - Fake agent processes for all three adapters.
  - Loop behavior for continue/rework/done transitions.
  - Missing-agent and auth-missing error paths.
- E2E (manual or gated):
  - Real CLI smoke tests on Windows for each supported agent.

## Setup and Installation Strategy
- Distribution:
  - Publish to PyPI (`cli-runner`) as canonical distribution path.
- Runtime dependencies:
  - Keep hard runtime dependencies minimal.
  - Keep PTY-related support optional and disabled by default.
- Setup UX:
  - Add `cli-runner doctor` to validate:
    - Agent executable discovery.
    - Required auth environment variables.
    - Basic command invocation readiness.

## Security and Safety
- Never use shell string interpolation for prompt execution (`shell=False` list args only).
- Do not log secrets or echo credential env var values.
- Bound loops by default and make exit states machine-checkable.
- Keep strict completion on by default, with explicit override.

## Risks and Mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| Agent CLI behavior drift | Medium | Isolate CLI specifics in adapters and test adapters independently |
| Status protocol not followed by agent output | High | Keep strict parser + fallback gating + explicit test fixtures |
| Windows path/encoding edge cases | High | Maintain `.cmd` resolution tests and UTF-8 decode with replacement |
| Over-scoping v1 | High | Enforce guardrails and move multi-agent to M4 |

## First 2 Weeks Execution Plan
### Week 1
- Implement adapter interface and wire `--agent`.
- Add `gemini` and `claude` adapters alongside `codex`.
- Add binary/auth detection and user-facing error messages.
- Add/update tests for new adapter paths.

### Week 2
- Add `doctor` command and finalize troubleshooting docs.
- Complete Windows CI matrix and packaging checks.
- Finalize README usage examples for all three agents.
- Cut pre-release tag and run install smoke tests on clean environment.

## Post-v1 Backlog
- Multi-agent mode (`--agents` chain/parallel) with deterministic merge policy.
- Optional pretty output mode that does not affect core protocol reliability.
- Cross-platform expansion (Linux/macOS) after Windows maturity.
