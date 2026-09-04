import asyncio
import json

import pytest

from agentveto import VetoError, evaluate, guard
from agentveto.tracer import Tracer


@pytest.fixture
def tracer(tmp_path):
    return Tracer(str(tmp_path / "v.db"), auto_patch=False)


def latest_span(tracer):
    run = tracer.store.latest_run()
    return tracer.store.get_spans(run["id"])[-1]


def span_veto(span):
    attrs = json.loads(span["attributes"] or "{}")
    return attrs.get("veto")


# ---------------------------------------------------------------- evaluate

def test_default_is_allow_when_no_rule_matches():
    p = {"default": "allow", "rules": []}
    d = evaluate(p, "anything")
    assert d.effect == "allow"
    assert d.allowed


def test_default_can_be_deny():
    p = {"default": "deny", "rules": []}
    assert evaluate(p, "anything").effect == "deny"


def test_first_matching_rule_wins():
    p = {
        "default": "allow",
        "rules": [
            {"name": "one", "action": "refund", "effect": "allow"},
            {"name": "two", "action": "refund", "effect": "deny"},  # must not win
        ],
    }
    d = evaluate(p, "refund", {})
    assert d.rule == "one"
    assert d.effect == "allow"


def test_rule_precedence_is_explicit():
    p = {
        "default": "allow",
        "rules": [
            {"name": "blocked", "action": "refund", "effect": "deny",
             "when": {"amount": {"gt": 100}}},
            {"name": "allowed", "action": "refund", "effect": "allow"},
        ],
    }
    assert evaluate(p, "refund", {"amount": 500}).effect == "deny"
    assert evaluate(p, "refund", {"amount": 10}).effect == "allow"


def test_wildcard_actions():
    p = {"default": "deny", "rules": [{"name": "w", "action": "send_*", "effect": "allow"}]}
    assert evaluate(p, "send_email").allowed
    assert evaluate(p, "send_sms").allowed
    assert evaluate(p, "receive_email").effect == "deny"


def test_rule_without_when_matches_every_call_for_that_action():
    p = {"default": "allow", "rules": [{"name": "n", "action": "rm", "effect": "deny"}]}
    assert evaluate(p, "rm", {}).effect == "deny"
    assert evaluate(p, "rm", {"path": "/tmp"}).effect == "deny"


def test_when_operators_and():
    p = {
        "default": "allow",
        "rules": [
            {
                "name": "cap",
                "action": "refund",
                "effect": "deny",
                "when": {
                    "amount_usd": {"gt": 250, "lte": 1000},  # both must hold
                    "currency": {"eq": "USD"},
                },
            },
        ],
    }
    assert evaluate(p, "refund", {"amount_usd": 500, "currency": "USD"}).effect == "deny"
    assert evaluate(p, "refund", {"amount_usd": 1000, "currency": "USD"}).effect == "deny"
    assert evaluate(p, "refund", {"amount_usd": 1001, "currency": "USD"}).effect == "allow"
    assert evaluate(p, "refund", {"amount_usd": 500, "currency": "EUR"}).effect == "allow"


def test_when_in_operator():
    p = {"default": "allow", "rules": [
        {"name": "no-bulk", "action": "email", "effect": "deny",
         "when": {"to": {"in": ["all@corp.com", "everyone@corp.com"]}}},
    ]}
    assert evaluate(p, "email", {"to": "all@corp.com"}).effect == "deny"
    assert evaluate(p, "email", {"to": "someone@corp.com"}).allowed


def test_exists_operator():
    p = {"default": "allow", "rules": [
        {"name": "r", "action": "go", "effect": "deny", "when": {"deploy": {"exists": True}}},
    ]}
    assert evaluate(p, "go", {"deploy": True}).effect == "deny"
    assert evaluate(p, "go", {}).allowed


def test_nested_paths_and_missing_fields_are_false():
    p = {"default": "deny", "rules": [
        {"name": "r", "action": "call", "effect": "allow",
         "when": {"destination.region": {"eq": "cn-east"}}},
    ]}
    assert evaluate(p, "call", {"destination": {"region": "cn-east"}}).allowed
    assert evaluate(p, "call", {"destination": {"region": "us-west"}}).effect == "deny"
    assert evaluate(p, "call", {"destination": {}}).effect == "deny"


def test_rule_without_explicit_effect_defaults_to_deny():
    p = {"default": "allow", "rules": [{"name": "r", "action": "x"}]}
    assert evaluate(p, "x").effect == "deny"


def test_decision_is_deterministic_and_readable():
    p = {"default": "deny", "rules": [{"name": "r", "action": "refund", "effect": "ask",
                                       "when": {"amount": {"gt": 100}}}]}
    a = evaluate(p, "refund", {"amount": 250})
    b = evaluate(p, "refund", {"amount": 250})
    assert a == b
    assert a.effect == "ask"
    assert "ask" in str(a)
    assert "r" in str(a)


# ---------------------------------------------------------------- guard

def _policy():
    return {
        "default": "allow",
        "rules": [
            {"name": "no-refund-over-250", "action": "issue_refund", "effect": "deny",
             "when": {"amount_usd": {"gt": 250}},
             "reason": "Over the agent authority line."},
            {"name": "ask-on-delete", "action": "delete_customer", "effect": "ask",
             "reason": "Deleting a customer record needs a human."},
        ],
    }


def test_guard_allows_and_returns_result(tracer):
    calls = []

    @guard(_policy(), action="issue_refund")
    def refund(order_id, amount_usd):
        calls.append(amount_usd)
        return {"status": "ok"}

    with tracer.start_run("r"):
        assert refund("A-1", 100) == {"status": "ok"}
        assert refund(order_id="A-2", amount_usd=150) == {"status": "ok"}

    assert calls == [100, 150]
    run = tracer.store.latest_run()
    assert run["span_count"] == 2
    for s in tracer.store.get_spans(run["id"]):
        assert s["status"] == "ok"
        assert span_veto(s)["effect"] == "allow"


def test_guard_deny_blocks_and_is_recorded(tracer):
    calls = []

    @guard(_policy(), action="issue_refund")
    def refund(order_id, amount_usd):
        calls.append(amount_usd)

    with pytest.raises(VetoError) as ei:
        with tracer.start_run("r"):
            refund("A-1", 500)

    assert calls == []  # never executed
    assert ei.value.decision.rule == "no-refund-over-250"
    assert ei.value.decision.effect == "deny"

    span = latest_span(tracer)
    assert span["status"] == "error"
    assert "no-refund-over-250" in span["error"]
    v = span_veto(span)
    assert v["effect"] == "deny"
    assert v["rule"] == "no-refund-over-250"
    assert "authority" in v["reason"]


def test_guard_positional_args_map_to_payload_names(tracer):
    calls = []

    @guard(_policy(), action="issue_refund")
    def refund(order_id, amount_usd):
        calls.append(amount_usd)

    with tracer.start_run("r"):
        with pytest.raises(VetoError):
            refund("A-1", 999)  # positional; amount_usd recovered via signature

    assert calls == []
    v = span_veto(latest_span(tracer))
    assert v["effect"] == "deny"
    assert v["rule"] == "no-refund-over-250"


def test_guard_ask_fails_closed_without_human(tracer):
    calls = []

    @guard(_policy(), action="delete_customer", prompter=lambda d, p: False)
    def delete_customer(customer_id):
        calls.append(customer_id)

    with tracer.start_run("r"):
        with pytest.raises(VetoError):
            delete_customer("C-9")

    assert calls == []
    span = latest_span(tracer)
    v = span_veto(span)
    assert v["effect"] == "deny"  # resolved: ask -> declined (fail closed)
    assert v["asked"] is True
    assert span["status"] == "error"
    assert "declined" in span["error"]


def test_guard_ask_approves_and_runs(tracer):
    calls = []

    @guard(_policy(), action="delete_customer", prompter=lambda d, p: True)
    def delete_customer(customer_id):
        calls.append(customer_id)
        return "deleted"

    with tracer.start_run("r"):
        assert delete_customer("C-9") == "deleted"

    assert calls == ["C-9"]
    v = span_veto(latest_span(tracer))
    assert v["effect"] == "allow"
    assert v["asked"] is True


def test_guard_without_record_still_enforces():
    calls = []

    @guard(_policy(), action="issue_refund", record=False)
    def refund(amount_usd):
        calls.append(amount_usd)

    with pytest.raises(VetoError):
        refund(300)
    assert calls == []
    assert refund(100) is None
    assert calls == [100]


def test_guard_async_allow_and_deny():
    calls = []

    @guard(_policy(), action="issue_refund", record=False)  # no run context in this test
    async def refund(amount_usd):
        calls.append(amount_usd)
        return amount_usd

    assert asyncio.run(refund(100)) == 100
    with pytest.raises(VetoError):
        asyncio.run(refund(999))
    assert calls == [100]


def test_evaluate_is_pure_only_guard_raises():
    p = {"default": "allow", "rules": [{"name": "r", "action": "x", "effect": "deny",
                                        "reason": "because"}]}
    d = evaluate(p, "x")
    assert d.effect == "deny"

    @guard(p, action="x", record=False)
    def x():
        return 1

    with pytest.raises(VetoError):
        x()


def test_report_marks_a_denied_call(tracer, tmp_path):
    from agentveto.report import report

    @guard(_policy(), action="issue_refund")
    def refund(amount_usd):
        return amount_usd

    with tracer.start_run("policy-run"):
        with pytest.raises(VetoError):
            refund(500)

    out = report(store=tracer.store, out=str(tmp_path / "vr.html"))
    html = open(out, encoding="utf-8").read()
    assert "tag veto" in html
    assert "no-refund-over-250" in html


def test_default_guard_records_everything_even_without_policy(tracer):
    @guard()  # no policy: allow, but the decision is still audited
    def f(x):
        return x * 2

    with tracer.start_run("r"):
        assert f(21) == 42

    span = latest_span(tracer)
    assert span["status"] == "ok"
    assert span_veto(span)["effect"] == "allow"
