# Changelog

All notable changes to agentveto are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project adheres to
[Semantic Versioning](https://semver.org/) as soon as we hit 1.0.

## [Unreleased]

### Added

- V1 preview: `@guard(policy, action="...")` runtime policy gate. Deny,
  ask-with-fail-closed, plain-dict policy with `when` clauses over dot
  paths. Every decision is written into the trace as a span attribute and
  surfaces in the HTML view as a `veto` tag.
- `policy_io` module + `agentveto policy {show,validate,explain}` CLI for
  inspecting a JSON policy without running code.
- MCP server (`agentveto-mcp`) exposing `evaluate_policy`, `explain_policy`,
  `validate_policy`, `load_policy_file`. Install with
  `pip install 'agentveto[mcp]'`.
- String and length operators: `endswith`, `startswith`, `contains`,
  `len_eq`, `len_gt`, `len_lt`. Cross-type comparisons fail closed (`string > 0`
  -> `false`, not an exception).
- `reason` accepts a `{lang: text}` dict for bilingual errors. Locale
  picked from `AGENTVETO_LANG` > `LANG` > `en`.
- MkDocs documentation site (`docs/`).

## [0.1.0] - 2026-09-04

### Added

- V0 release: deterministic replay, cost attribution, step-level audit.
- `@agentveto.trace(kind="tool")` decorator for explicit spans.
- Auto-instrumentation of installed `openai` and `anthropic` SDKs.
- Single-file HTML report (no CDN, no login, opens offline).
- SQLite-backed `Store` with WAL mode; `init(replay=True)` for free replays.
- `agentveto demo`, `agentveto list`, `agentveto report --run <id>`,
  `agentveto serve` CLI.
- 86 passing tests covering record/replay, the policy engine, the MCP server,
  and bilingual reasons.