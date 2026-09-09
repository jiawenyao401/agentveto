"""Tests for the MCP server module.

We don't drive the full JSON-RPC loop here (that's the MCP SDK's job to
keep working). What we test is:

- the build_server() factory returns a FastMCP that registered our tools
- the policy coercion helpers accept dict, JSON string, and file path
- each tool's underlying implementation produces the right shape
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from agentveto import mcp as mcp_module


P = {
    "default": "allow",
    "rules": [
        {
            "name": "big-refund",
            "action": "issue_refund",
            "effect": "ask",
            "when": {"amount_usd": {"gt": 250}},
            "reason": "too big",
        },
        {
            "name": "external-mail",
            "action": "send_*",
            "effect": "deny",
            "when": {"to": {"endswith": "@external.com"}},
            "reason": "no",
        },
    ],
}


# ----------------- coercion helpers ----------------------------------------


def test_coerce_dict():
    assert mcp_module._coerce_policy(P) == P


def test_coerce_json_string():
    js = json.dumps(P)
    assert mcp_module._coerce_policy(js) == P


def test_coerce_path(tmp_path):
    fp = tmp_path / "pol.json"
    fp.write_text(json.dumps(P), encoding="utf-8")
    assert mcp_module._coerce_policy(str(fp)) == P


def test_coerce_invalid():
    with pytest.raises(mcp_module.PolicyError):
        mcp_module._coerce_policy(42)


def test_parse_payload_dict():
    assert mcp_module._parse_payload({"a": 1}) == {"a": 1}


def test_parse_payload_string():
    assert mcp_module._parse_payload('{"a": 2}') == {"a": 2}


def test_parse_payload_empty_string():
    assert mcp_module._parse_payload("") == {}
    assert mcp_module._parse_payload("   ") == {}


def test_parse_payload_invalid_string():
    with pytest.raises(json.JSONDecodeError):
        mcp_module._parse_payload("not json")


# ----------------- the server itself ----------------------------------------


def test_build_server_registers_tools():
    server = mcp_module.build_server(initial_policy=P)
    # FastMCP exposes its tool manager; check it has at least our four tools.
    tool_mgr = getattr(server, "_tool_manager", None) or getattr(server, "_tools", None)
    assert tool_mgr is not None, "FastMCP tool manager missing"
    names = set()
    if hasattr(tool_mgr, "list_tools"):
        names = {t.name for t in tool_mgr.list_tools()}
    elif hasattr(tool_mgr, "_tools"):
        names = set(tool_mgr._tools.keys())
    expected = {"evaluate_policy", "explain_policy", "validate_policy", "load_policy_file"}
    missing = expected - names
    assert not missing, f"tools not registered: {missing}; got {names}"


def test_evaluate_policy_no_loaded_returns_allow():
    server = mcp_module.build_server()
    fn = _find_tool(server, "evaluate_policy")
    out = fn.fn(action="send_email", payload={"to": "x@y.com"})
    assert out["effect"] == "allow"
    assert "note" in out


def test_evaluate_policy_with_loaded():
    server = mcp_module.build_server(initial_policy=P)
    fn = _find_tool(server, "evaluate_policy")
    out = fn.fn(action="issue_refund", payload={"amount_usd": 412})
    assert out["effect"] == "ask"
    assert out["rule"] == "big-refund"


def test_evaluate_policy_override():
    server = mcp_module.build_server(initial_policy=P)
    fn = _find_tool(server, "evaluate_policy")
    override = {"default": "deny", "rules": []}
    out = fn.fn(action="anything", payload={}, policy=override)
    assert out["effect"] == "deny"


def test_explain_policy_returns_verdicts():
    server = mcp_module.build_server(initial_policy=P)
    fn = _find_tool(server, "explain_policy")
    out = fn.fn(action="issue_refund", payload='{"amount_usd": 412}')
    assert out["action"] == "issue_refund"
    assert out["decision"]["rule"] == "big-refund"
    assert isinstance(out["rules"], list)
    assert len(out["rules"]) == 2


def test_validate_policy_ok():
    server = mcp_module.build_server()
    fn = _find_tool(server, "validate_policy")
    out = fn.fn(policy=json.dumps(P))
    assert out["valid"] is True
    assert out["rule_count"] == 2


def test_validate_policy_bad():
    server = mcp_module.build_server()
    fn = _find_tool(server, "validate_policy")
    out = fn.fn(policy='{"default":"maybe","rules":[]}')
    assert out["valid"] is False
    assert "default" in out["error"]


def test_load_policy_file_remembers(tmp_path):
    fp = tmp_path / "p.json"
    fp.write_text(json.dumps(P), encoding="utf-8")
    server = mcp_module.build_server()
    fn = _find_tool(server, "load_policy_file")
    out = fn.fn(path=str(fp))
    assert out["loaded"].endswith("p.json")
    # subsequent evaluate uses the loaded policy
    eval_fn = _find_tool(server, "evaluate_policy")
    out2 = eval_fn.fn(action="issue_refund", payload={"amount_usd": 412})
    assert out2["effect"] == "ask"


# ----------------- internals --------------------------------------------------


def _find_tool(server, name):
    """FastMCP wraps tool functions in a structure with `.fn`. Return the wrapper."""
    tool_mgr = getattr(server, "_tool_manager", None)
    if tool_mgr and hasattr(tool_mgr, "_tools"):
        for t in tool_mgr._tools.values():
            if getattr(t, "name", None) == name:
                return t
    raise RuntimeError(f"tool {name!r} not registered")
