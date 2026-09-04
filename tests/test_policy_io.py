"""Tests for policy_io: load/validate/save and the explain trace."""

import json
import os
import tempfile

import pytest

from agentveto.policy_io import (
    Explanation,
    PolicyError,
    explain,
    load_policy,
    load_policy_from_dict,
    save_policy,
)


POLICY = {
    "default": "allow",
    "rules": [
        {"name": "no-marketing", "action": "send_email", "effect": "deny",
         "reason": "No marketing email without a human."},
        {"name": "big-refund", "action": "issue_refund", "effect": "ask",
         "when": {"amount_usd": {"gt": 250}}, "reason": "Refunds > $250 need approval."},
        {"name": "export-pii", "action": "export_pii", "effect": "deny",
         "reason": "PII export is blocked."},
        {"name": "external-mail", "action": "send_*", "effect": "deny",
         "when": {"to": {"endswith": "@external.com"}},
         "reason": "External recipients blocked."},
    ],
}


# ------------------ loading --------------------------------------------------


def test_load_minimal():
    p = load_policy_from_dict({"default": "allow", "rules": []})
    assert p["default"] == "allow"


def test_load_defaults():
    p = load_policy_from_dict({"rules": []})
    assert p["default"] == "allow"


def test_reject_non_object():
    with pytest.raises(PolicyError, match="must be a JSON object"):
        load_policy_from_dict([])


def test_reject_bad_default():
    with pytest.raises(PolicyError, match="default must be"):
        load_policy_from_dict({"default": "maybe", "rules": []})


def test_reject_bad_effect():
    with pytest.raises(PolicyError, match="effect must be"):
        load_policy_from_dict({"rules": [{"effect": "explode"}]})


def test_reject_duplicate_name():
    with pytest.raises(PolicyError, match="duplicate name"):
        load_policy_from_dict({
            "rules": [
                {"name": "x", "action": "a", "effect": "deny"},
                {"name": "x", "action": "b", "effect": "deny"},
            ]
        })


def test_reject_empty_name():
    with pytest.raises(PolicyError, match="non-empty string"):
        load_policy_from_dict({"rules": [{"name": "  ", "effect": "deny"}]})


def test_reject_unknown_operator():
    with pytest.raises(PolicyError, match="unknown operator"):
        load_policy_from_dict({"rules": [
{"name": "x", "effect": "deny", "when": {"a": {"near": 1}}}
]})


def test_save_load_roundtrip():
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        path = f.name
    try:
        save_policy(POLICY, path)
        again = load_policy(path)
        assert again == POLICY
    finally:
        os.unlink(path)


# ------------------ explain -------------------------------------------------


def test_explain_default_allow():
    e = explain(POLICY, "list_orders", {})
    assert e.decision.effect == "allow"
    assert e.decision.rule == ""
    assert all(not r.matched for r in e.rules)


def test_explain_first_match_wins():
    e = explain(POLICY, "send_email", {"to": "x@external.com", "subject": "s", "body": "b"})
    assert e.decision.effect == "deny"
    assert e.decision.rule == "no-marketing"  # earlier rule wins
    # the wildcard rule (blanket-deny) never gets a chance to run


def test_explain_action_filter():
    e = explain(POLICY, "issue_refund", {"amount_usd": 50})
    # big-refund has amount_usd.gt(250) which 50 does not satisfy -> skip
    # no other rule matches issue_refund -> default allow
    assert e.decision.effect == "allow"


def test_explain_amount_threshold():
    # remove blanket-deny from the rule set for this scenario
    P = {"default": "allow", "rules": POLICY["rules"][:2]}
    e = explain(P, "issue_refund", {"amount_usd": 412})
    assert e.decision.effect == "ask"
    assert e.decision.rule == "big-refund"
    # the big-refund verdict should report amount_usd > 250 = true
    path_verdict = e.rules[1].paths[0]
    assert path_verdict.matched is True
    assert "gt 250" in path_verdict.detail


def test_explain_endswith_match():
    P = {"default": "allow", "rules": [POLICY["rules"][3]]}
    e = explain(P, "send_sms", {"to": "a@external.com"})
    assert e.decision.effect == "deny"
    assert e.decision.rule == "external-mail"
    assert e.rules[0].matched is True


def test_explain_endswith_no_match():
    P = {"default": "allow", "rules": [POLICY["rules"][3]]}
    e = explain(P, "send_sms", {"to": "a@internal.com"})
    assert e.decision.effect == "allow"


def test_explain_payload_as_string():
    P = {"default": "allow", "rules": [{"action": "x", "effect": "deny",
                                          "when": {"value": {"len_gt": 5}}}]}
    e = explain(P, "x", "this is a long string")  # wrapped as {"value": ...}
    assert e.decision.effect == "deny"


def test_explain_as_dict_roundtrip():
    e = explain(POLICY, "send_email", {"to": "x@y.com"})
    d = e.as_dict()
    assert d["action"] == "send_email"
    assert isinstance(d["rules"], list)
    assert "decision" in d
    # re-serialize, must not crash
    json.dumps(d)


# ------------------ string operator coverage in the evaluator --------------


def test_string_endswith_in_evaluate():
    from agentveto.veto import evaluate
    P = {"rules": [{"name": "x", "action": "send_*", "effect": "deny",
                    "when": {"to": {"endswith": "@external.com"}}}]}
    assert evaluate(P, "send_email", {"to": "a@external.com"}).effect == "deny"
    assert evaluate(P, "send_email", {"to": "a@internal.com"}).effect == "allow"


def test_string_startswith_in_evaluate():
    from agentveto.veto import evaluate
    P = {"rules": [{"name": "x", "action": "*", "effect": "deny",
                    "when": {"name": {"startswith": "admin"}}}]}
    assert evaluate(P, "y", {"name": "admin_user"}).effect == "deny"
    assert evaluate(P, "y", {"name": "user"}).effect == "allow"


def test_string_contains_in_evaluate():
    from agentveto.veto import evaluate
    P = {"rules": [{"name": "x", "action": "*", "effect": "deny",
                    "when": {"body": {"contains": "password"}}}]}
    assert evaluate(P, "send", {"body": "your password is ..."}).effect == "deny"
    assert evaluate(P, "send", {"body": "no secrets here"}).effect == "allow"


def test_len_operators_in_evaluate():
    from agentveto.veto import evaluate
    P = {"rules": [{"name": "x", "action": "*", "effect": "deny",
                    "when": {"body": {"len_gt": 100}}}]}
    assert evaluate(P, "send", {"body": "x" * 200}).effect == "deny"
    assert evaluate(P, "send", {"body": "short"}).effect == "allow"