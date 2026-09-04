"""Runtime policy gates - the Veto layer.

V0 records what an agent did. This layer decides, *before* a dangerous call
goes out, whether the agent is allowed to make it at all. That is the product:
not a post-mortem, a speed bump that actually stops things.

Design constraints, same as the rest of the package:

- Zero required dependencies. A policy is a plain dict. Loading it from YAML
  or JSON is the user's choice; we do not force a parser on them.
- Deterministic and auditable. The same policy + payload always yields the
  same decision, and every decision is written into the trace as a span, so a
  blocked call shows up in the same report as everything else.
- Fail closed. When a rule says "ask" and there is no human at the keyboard,
  the call is denied - never allowed by default.
- First matching rule wins. Policy authors control precedence by ordering
  their rules, exactly like firewall rules.

The full grammar of a policy:

    {
        "default": "allow",            # what to do when no rule matches
        "rules": [
            {
                "name": "no-bulk-email",         # recorded in the trace
                "action": "send_email",          # exact, "send_*", or "*"
                "effect": "deny",                # allow | deny | ask
                "when": {                        # optional: all must hold
                    "recipients": {"in": ["all-customers@acme.com"]},
                    "body.length": {"gt": 1000},
                },
                "reason": "Marketing mail must go through a human.",
            },
        ],
    }

Supported comparison operators in "when": eq, ne, gt, gte, lt, lte, in,
exists. Paths are dot-separated field lookups into the call payload.
"""

from __future__ import annotations

import functools
import inspect
import sys
from dataclasses import dataclass
from typing import Any, Callable

EFFECTS = ("allow", "deny", "ask")
OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "exists"}

_MISSING = object()


@dataclass(frozen=True)
class Decision:
    """The result of evaluating one action against a policy."""

    effect: str
    action: str | None = None
    rule: str | None = None
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.effect == "allow"

    def __str__(self) -> str:
        where = f"rule '{self.rule}'" if self.rule else "default"
        why = f": {self.reason}" if self.reason else ""
        return f"[{where}] {self.effect} {self.action or ''}{why}".strip()


class VetoError(Exception):
    """Raised when a guarded call is denied or an approval is declined."""

    def __init__(self, decision: Decision):
        self.decision = decision
        super().__init__(str(decision))


# ---------------------------------------------------------------- matching

def _action_match(want: str, action: str) -> bool:
    if want == "*":
        return True
    if want.endswith("*"):
        return action.startswith(want[:-1])
    return want == action


def _path_get(payload: Any, path: str) -> Any:
    cur = payload
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return _MISSING
    return cur


def _apply(op: str, actual: Any, expected: Any) -> bool:
    if actual is _MISSING:
        # A field that is not there does not equal null, and it is not
        # greater than anything. Only "ne" treats absence as a difference.
        return False
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "gt":
        return actual > expected
    if op == "gte":
        return actual >= expected
    if op == "lt":
        return actual < expected
    if op == "lte":
        return actual <= expected
    if op == "in":
        try:
            return actual in expected
        except TypeError:
            return False
    if op == "exists":
        return bool(expected)  # caller already knows actual is present
    return False


def _cond_holds(path: str, cond: Any, payload: Any) -> bool:
    actual = _path_get(payload, path)
    # Operators always come from a fixed set; a payload that happens to be a
    # dict can never be mistaken for an operator block.
    if isinstance(cond, dict) and cond and set(cond).issubset(OPS):
        for op, expected in cond.items():
            if op == "exists":
                present = actual is not _MISSING
                if present != bool(expected):
                    return False
            elif actual is _MISSING:
                if op != "ne":
                    return False
            elif not _apply(op, actual, expected):
                return False
        return True
    if isinstance(cond, dict) and not cond:
        return actual is not _MISSING
    return actual is not _MISSING and _apply("eq", actual, cond)


def _rule_matches(rule: dict, action: str, payload: Any) -> bool:
    if not _action_match(str(rule.get("action", "*")), action):
        return False
    when = rule.get("when")
    if not when:
        return True
    if not isinstance(when, dict):
        return False
    for path, cond in when.items():
        if not _cond_holds(path, cond, payload):
            return False
    return True


# ---------------------------------------------------------------- evaluate

def evaluate(policy: dict | None, action: str, payload: Any = None) -> Decision:
    """Return the decision for one action. Pure and deterministic.

    A missing policy allows everything (open by default at the evaluator
    level; guard() records that fact so it stays auditable).
    """
    policy = policy or {}
    payload = payload if payload is not None else {}
    for rule in policy.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        if _rule_matches(rule, action, payload):
            effect = rule.get("effect", "deny")  # a rule without an effect closes the door
            if effect not in EFFECTS:
                effect = "deny"
            return Decision(
                effect=effect,
                action=action,
                rule=str(rule.get("name") or ""),
                reason=str(rule.get("reason") or ""),
            )
    return Decision(
        effect="allow" if policy.get("default") != "deny" else "deny",
        action=action,
    )


# ---------------------------------------------------------------- guard

def _bind_payload(fn: Callable, args: tuple, kwargs: dict) -> dict:
    """Map positional args onto parameter names so policy 'when' fields are
    stable regardless of how the caller invoked the tool."""
    try:
        bound = inspect.signature(fn).bind(*args, **kwargs)
        bound.apply_defaults()
        return dict(bound.arguments)
    except (TypeError, ValueError):
        return {"args": args, "kwargs": kwargs}


def _default_prompter(decision: Decision, payload: Any) -> bool:
    """Ask the human on the terminal. Denies when no terminal is attached."""
    if not sys.stdin.isatty():
        return False
    print()
    print(f"[agentveto] {decision}")
    try:
        ans = input("[agentveto] approve? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in ("y", "yes")


def _active_tracer():
    """The tracer that owns the run in progress, if any; else the singleton.

    A guarded tool can fire from inside anyone's start_run(); recording into
    that same store is what makes the veto visible in the caller's report.
    """
    from ._context import current_tracer

    t = current_tracer.get()
    if t is not None:
        return t
    from . import get_tracer

    return get_tracer()


def guard(
    policy: dict | None = None,
    *,
    action: str | None = None,
    record: bool = True,
    prompter: Callable[[Decision, Any], bool] | None = None,
):
    """Decorate a tool/function so every call is checked before it runs.

        @guard(POLICY, action="send_email")
        def send_email(to, subject, body): ...

    A "deny" (or an unapproved "ask") raises VetoError and the wrapped
    function never executes - fail closed. Every decision is recorded onto
    the trace as an attribute of the tool span, so blocked calls appear in
    the same report as the agent steps around them.

    prompter(decision, payload) -> bool decides what "ask" means in your
    environment. The default prompts on a terminal and denies everywhere
    else.
    """

    def decorate(fn):
        act = action or fn.__name__
        is_async = inspect.iscoroutinefunction(fn)

        def _gate(args, kwargs) -> tuple[dict, Decision, str]:
            """Return (payload, decision, resolved_effect) or raise VetoError.

            resolved_effect collapses "ask": an approved ask becomes "allow",
            a declined ask becomes an exception. Deny always raises.
            """
            payload = _bind_payload(fn, args, kwargs)
            decision = evaluate(policy, act, payload)
            if decision.effect == "allow":
                return payload, decision, "allow"
            if decision.effect == "ask":
                approver = prompter or _default_prompter
                try:
                    approved = bool(approver(decision, payload))
                except Exception:
                    approved = False
                if approved:
                    return payload, decision, "allow"
                note = " - approval declined (fail closed)"
                reason = decision.reason + note if decision.reason else "approval declined (fail closed)"
                raise VetoError(
                    Decision("ask", action=act, rule=decision.rule, reason=reason)
                )
            raise VetoError(decision)

        def _mark(span: Any, payload: dict, decision: Decision, resolved: str) -> None:
            span.set_attribute(
                "veto",
                {
                    "action": act,
                    "effect": resolved,
                    "rule": decision.rule,
                    "reason": decision.reason,
                    "asked": decision.effect == "ask",
                },
            )
            span.set_io(input=payload)

        if is_async:

            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                if not record:
                    _gate(args, kwargs)
                    return await fn(*args, **kwargs)
                with _active_tracer().start_span(act, kind="tool") as span:
                    try:
                        payload, decision, resolved = _gate(args, kwargs)
                    except VetoError as exc:
                        _mark(span, _bind_payload(fn, args, kwargs), exc.decision, "deny")
                        raise
                    _mark(span, payload, decision, resolved)
                    result = await fn(*args, **kwargs)
                    span.set_io(output=result)
                    return result

            return async_wrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not record:
                _gate(args, kwargs)
                return fn(*args, **kwargs)
            with _active_tracer().start_span(act, kind="tool") as span:
                try:
                    payload, decision, resolved = _gate(args, kwargs)
                except VetoError as exc:
                    _mark(span, _bind_payload(fn, args, kwargs), exc.decision, "deny")
                    raise
                _mark(span, payload, decision, resolved)
                result = fn(*args, **kwargs)
                span.set_io(output=result)
                return result

        return wrapper

    return decorate

