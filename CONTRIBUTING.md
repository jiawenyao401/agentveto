# Contributing to agentveto

Thanks for your interest. agentveto is the runtime control layer for AI agents:
**replay** what an agent did, **prove** it with an auditable trail, and **veto**
actions before they execute.

## Scope of v0

v0 is intentionally small: deterministic replay + cost attribution + step-level
audit, with zero required dependencies. Keep it that way. If a change pulls in a
new required dependency or a heavy framework, open an issue first.

## Dev setup

```bash
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

## Before opening a PR

- `pytest -q` is green.
- Code is formatted with `ruff format` / `black` (line length 100).
- New behavior has a test.
- Public APIs stay backward compatible within a minor version.

## Reporting security issues

Do not open a public issue for vulnerabilities. Email the maintainer directly.
