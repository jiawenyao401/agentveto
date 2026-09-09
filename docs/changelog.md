# Changelog

All notable changes to agentveto are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project adheres to
[Semantic Versioning](https://semver.org/) as soon as we hit 1.0.

## [Unreleased]

### Added

- **V2 "Prove": tamper-evident, signed evidence.** New `agentveto/prove.py`
  turns recorded runs into evidence an auditor can verify offline.
  - Canonical (sorted-key, compact) SHA-256 digest of every run: the run row
    plus all its spans, ordered by `seq`, hashed exactly as stored.
  - Runs are linked into a hash chain anchored at a genesis value, so each block
    transitively covers the whole history.
  - Optional Ed25519 signing of the chain head via `cryptography`. Because the
    head covers every earlier block, one signature authenticates everything.
    Install with `pip install 'agentveto[sign]'`.
  - Portable `.evd` evidence files: embed the target run's full data plus the
    digest chain, so a third party verifies with the file alone — no database,
    no network, no account.
  - Tamper detection that names its target: editing one byte in one span makes
    verification fail and report which run is wrong.
- `agentveto prove {keygen,sign,export}` and `agentveto verify` CLI commands.
  `verify` takes an `.evd` file, a `.db` file, or a directory; exits `0`/`1` so
  it drops into CI.
- Python API: `keygen`, `sign_db`, `export_evidence`, `verify_db`,
  `verify_evidence`, `verify_evidence_file`, and a `Verification` dataclass
  exposing `ok` plus per-check `(name, ok, detail)`.
- New `evidence` table in the SQLite schema (pos, run_id, prev_hash,
  run_digest, hash, signature, public_key, signed_at). Written only by
  `prove sign` — never by the tracing hot path.

### Notes

- Prove is integrity for what was recorded, not proof that the record is true.
  Anyone with write access *before* you sign can sign an edited record, so sign
  at the moment you want to freeze it. Documented in `docs/prove.md`.
- The chain is linear rather than a Merkle tree, deliberately: for one process's
  run history that is the right size.
- Formatting normalized to current `ruff format`, which the CI lint job enforces.
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