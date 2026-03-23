# Testing

## Scope
- CLI runner loop behavior and strict completion gating.
- Deterministic command resolution and status extraction.

## Execution
```powershell
pytest
```

For focused checks:
```powershell
pytest --no-cov tests/test_runner.py tests/test_main.py
```

## Notes
- Functional tests are the primary gate for runner behavior.
- Coverage settings are retained from the source project and can be tuned once the repo is fully decoupled.
