# Contributing to cli-ai-runner

Welcome! We are excited that you want to help improve `cli-ai-runner`.

## Local Development Setup

1.  **Clone the repository:**
    ```powershell
    git clone https://github.com/adw2323/cli-ai-runner.git
    cd cli-ai-runner
    ```

2.  **Create a virtual environment:**
    ```powershell
    python -m venv .venv
    .\.venv\Scripts\activate
    ```

3.  **Install in editable mode with dev dependencies:**
    ```powershell
    pip install -e .[dev]
    ```

## Running Tests

We use `pytest` for our test suite. All PRs must pass the test suite with at least **85% coverage**.

```powershell
# Run all tests
pytest

# Run with coverage report
pytest --cov=src/cli_ai_runner --cov-report=term-missing
```

## Project Structure

- `src/cli_ai_runner/`: Core logic.
- `src/cli_ai_runner/adapters/`: Agent-specific invocation strategies.
- `tests/`: Comprehensive test suite.
- `docs/`: User and architectural documentation.

## Standards

- **Typing:** Use type hints for all public functions.
- **Formatting:** We follow standard PEP 8 guidelines.
- **Documentation:** Any new feature must be documented in `docs/USER_GUIDE.md`.
