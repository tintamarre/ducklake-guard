# Development

## Running tests

Unit tests need no infrastructure:

```bash
uv run pytest tests/unit/ -x -q
```

Integration and end-to-end tests require a live PostgreSQL server, Hetzner S3 bucket, and DuckDB. They also need `TEST_USER_ACCESS_KEY` and `TEST_USER_SECRET_KEY` — S3 credentials from a separate Hetzner project for the test user. See `.env.sample` for the full list. Load credentials first:

```bash
set -a && source .env && set +a
uv run pytest tests/integration/ -m e2e -x -v
```

To run the full suite (unit + integration):

```bash
set -a && source .env && set +a
uv run pytest tests/ -x -q
```

## Linting and formatting

```bash
uv run ruff check --fix src/ tests/
uv run ruff format src/ tests/
```

## Pre-commit checklist

Before every commit, run linting and unit tests on changed files:

```bash
uv run ruff check --fix src/ tests/
uv run ruff format src/ tests/
uv run pytest tests/unit/ -x -q
```

If the change touches integration-relevant code, run the full test suite too.

Do not commit code that fails linting or tests.
