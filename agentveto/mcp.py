"""MCP server for agentveto.

Exposes the policy engine to MCP-aware clients (Claude Code, Cursor, etc.)
as three tools:

    evaluate_policy   - run one action through a policy, return Decision
    explain_policy    - return the full rule-by-rule verdict trace
    validate_policy   - check a JSON policy for structural errors

Run with:
    python -m agentveto.mcp path/to/policy.json

If no policy file is passed, every tool accepts the policy as a JSON string
argument so the client can change policy at runtime.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from .policy_io import (
    PolicyError,
    explain as explain_policy_fn,
    load_policy_from_dict,
)
from .veto import evaluate as evaluate_policy_fn


try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:
    raise SystemExit(
        "agentveto's MCP server needs the 'mcp' package.\n"
        "Install it with: pip install 'agentveto[mcp]'"
    ) from exc


def _coerce_policy(arg: Any) -> dict:
    """Accept a policy as a dict, a JSON string, or a path to a file."""
    if isinstance(arg, dict):
        return arg
    if isinstance(arg, str):
        s = arg.strip()
        if s.startswith("{"):
            return json.loads(s)
        # otherwise assume it's a file path
        with open(s, encoding="utf-8") as fh:
            return json.load(fh)
    raise PolicyError(f"policy must be a dict, JSON string, or path; got {type(arg).__name__}")


def _parse_payload(arg: Any) -> dict:
    if isinstance(arg, dict):
        return arg
    if isinstance(arg, str):
        s = arg.strip()
        if not s:
            return {}
        return json.loads(s)
    return {}


def build_server(initial_policy: dict | None = None) -> FastMCP:
    mcp = FastMCP("agentveto")
    state = {"policy": initial_policy}

    @mcp.tool()
    def evaluate_policy(action: str, payload: dict | str = "{}",
                        policy: dict | str | None = None) -> dict:
        """Evaluate one action against a policy and return the decision.

        Args:
            action:    the tool name being called (e.g. "send_email")
            payload:   the call's arguments as a JSON object or JSON string
            policy:    optional policy override; defaults to the loaded one
        """
        p = _coerce_policy(policy) if policy is not None else state["policy"]
        if p is None:
            return {"effect": "allow", "action": action, "rule": "",
                    "note": "no policy loaded; pass --policy or use policy arg"}
        d = evaluate_policy_fn(p, action, _parse_payload(payload))
        return {
            "effect": d.effect,
            "action": d.action,
            "rule": d.rule,
            "reason": d.reason,
            "allowed": d.allowed,
        }

    @mcp.tool()
    def explain_policy(action: str, payload: dict | str = "{}",
                       policy: dict | str | None = None) -> dict:
        """Explain which rule would fire for one action and why.

        Returns per-rule match verdicts with the path-level detail, plus
        the final decision. Same shape as the CLI's --format json output.
        """
        p = _coerce_policy(policy) if policy is not None else state["policy"]
        if p is None:
            return {"error": "no policy loaded; pass --policy or use policy arg"}
        return explain_policy_fn(p, action, _parse_payload(payload)).as_dict()

    @mcp.tool()
    def validate_policy(policy: dict | str) -> dict:
        """Validate a JSON policy and return its normalised form."""
        try:
            normalised = load_policy_from_dict(_coerce_policy(policy))
        except PolicyError as exc:
            return {"valid": False, "error": str(exc)}
        return {
            "valid": True,
            "default": normalised.get("default"),
            "rule_count": len(normalised.get("rules") or []),
        }

    @mcp.tool()
    def load_policy_file(path: str) -> dict:
        """Load a policy from a file path and remember it for later calls."""
        with open(path, encoding="utf-8") as fh:
            state["policy"] = load_policy_from_dict(json.load(fh))
        return {"loaded": path, "rule_count": len(state["policy"].get("rules") or [])}

    return mcp


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="agentveto-mcp",
        description="MCP server exposing the agentveto policy engine.",
    )
    parser.add_argument(
        "--policy", "-p", help="JSON policy file to load at startup"
    )
    args = parser.parse_args(argv)

    initial: dict | None = None
    if args.policy:
        with open(args.policy, encoding="utf-8") as fh:
            initial = load_policy_from_dict(json.load(fh))

    server = build_server(initial)
    server.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())