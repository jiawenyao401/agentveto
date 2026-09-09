"""Policy loading, validation, and explain.

The runtime evaluator in `veto.py` is a single pure function (evaluate).
This module is everything *around* it: read a policy from disk, sanity-check
it, and explain why a particular action against a particular payload would
produce the decision it does.

The point of `explain` is not to show off. It's that the first thing every
new user asks is "will this rule hit my case?". An offline CLI that answers
that in 200 ms beats a docs page.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from .veto import EFFECTS, OPS, Decision, evaluate

POLICY_SCHEMA_VERSION = 1


class PolicyError(ValueError):
    """Raised or malformed policies, with a message a human can act on."""


@dataclass
class PathVerdict:
    path: str
    cond: Any
    matched: bool
    detail: str  # "value 412.50 > 250" / "missing" / "not in set"


@dataclass
class RuleVerdict:
    index: int
    name: str
    action: str
    effect: str
    matched: bool
    paths: list[PathVerdict]  # empty if matched by action alone
    reason: str


@dataclass
class Explanation:
    action: str
    payload: Any
    default: str
    rules: list[RuleVerdict]
    decision: Decision

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "payload": self.payload,
            "default": self.default,
            "rules": [
                {
                    "index": r.index,
                    "name": r.name,
                    "action": r.action,
                    "effect": r.effect,
                    "matched": r.matched,
                    "reason": r.reason,
                    "paths": [
                        {"path": p.path, "cond": p.cond, "matched": p.matched, "detail": p.detail}
                        for p in r.paths
                    ],
                }
                for r in self.rules
            ],
            "decision": {
                "effect": self.decision.effect,
                "rule": self.decision.rule,
                "reason": self.decision.reason,
            },
        }


# ---------------------------------------------------------------- loading


def load_policy(path: str | os.PathLike) -> dict:
    """Load and validate a policy from a JSON file."""
    with open(path, encoding="utf-8") as fh:
        return load_policy_from_dict(json.load(fh))


def load_policy_from_dict(raw: Any) -> dict:
    """Validate a policy dict in memory. Raises the policy error on any
    structural problem; returns the dict (with a normalised 'default') on
    success."""
    if not isinstance(raw, dict):
        raise PolicyError(f"policy must be a JSON object, got {type(raw).__name__}")

    default = raw.get("default", "allow")
    if default not in EFFECTS:
        raise PolicyError(f"default must be one of {EFFECTS}, got {default!r}")
    raw = dict(raw)  # don't mutate the input
    raw["default"] = default

    rules = raw.get("rules")
    if rules is None:
        rules = []
        raw["rules"] = rules
    if not isinstance(rules, list):
        raise PolicyError("rules must be a list")

    seen: set[str] = set()
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise PolicyError(f"rule #{i} must be an object")
        name = rule.get("name")
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise PolicyError(f"rule #{i} name must be a non-empty string")
            if name in seen:
                raise PolicyError(f"rule #{i} duplicate name {name!r}")
            seen.add(name)
        effect = rule.get("effect", "deny")
        if effect not in EFFECTS:
            raise PolicyError(f"rule #{i} effect must be one of {EFFECTS}, got {effect!r}")
        action = rule.get("action", "*")
        if not isinstance(action, str):
            raise PolicyError(f"rule #{i} action must be a string")
        when = rule.get("when")
        if when is not None:
            if not isinstance(when, dict):
                raise PolicyError(f"rule #{i} when must be an object")
            for path, cond in when.items():
                if not isinstance(path, str):
                    raise PolicyError(f"rule #{i} when key must be a string")
                _validate_when(cond, f"rule #{i} when.{path}")
    return raw


def _validate_when(cond: Any, where: str) -> None:
    # Operator block: {"gt": 5, "in": [...]} - dict whose keys are operators
    if isinstance(cond, dict):
        unknown = set(cond) - OPS
        if unknown:
            raise PolicyError(f"{where}: unknown operator(s) {sorted(unknown)}")
        for op, expected in cond.items():
            if op == "in" and not isinstance(expected, (list, tuple, set, frozenset)):
                raise PolicyError(f"{where}.in expects a list, got {type(expected).__name__}")
        return
    # bare value -> implicit eq; nothing to validate


def save_policy(policy: dict, path: str | os.PathLike) -> None:
    """Write a validated policy as pretty-printed JSON."""
    load_policy_from_dict(policy)  # raises on invalid
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(policy, fh, indent=2, sort_keys=False, ensure_ascii=False)
        fh.write("\n")


# ---------------------------------------------------------------- explain


# Lazy import to avoid a circular dep (veto.py imports nothing from here).
def _matcher():
    from . import veto as _v

    return _v


def explain(policy: dict, action: str, payload: Any = None) -> Explanation:
    """Walk the rule set against one action and explain every match decision.

    The decision returned is exactly what `evaluate()` would return. The
    per-rule verdicts tell you which paths held, which failed, and why.
    """
    payload = payload if payload is not None else {}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    default = policy.get("default", "allow") if isinstance(policy, dict) else "allow"
    rules = (policy.get("rules") or []) if isinstance(policy, dict) else []
    v = _matcher()
    verdicts: list[RuleVerdict] = []
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("name") or f"rule-{i}")
        want_action = str(rule.get("action", "*"))
        effect = str(rule.get("effect", "deny"))
        reason = str(rule.get("reason") or "")
        action_ok = v._action_match(want_action, action)
        if not action_ok:
            verdicts.append(
                RuleVerdict(
                    index=i,
                    name=name,
                    action=want_action,
                    effect=effect,
                    matched=False,
                    paths=[
                        PathVerdict(
                            "__action__",
                            want_action,
                            False,
                            f"action {action!r} does not match {want_action!r}",
                        )
                    ],
                    reason=reason,
                )
            )
            continue
        when = rule.get("when") or {}
        paths: list[PathVerdict] = []
        matched = True
        for path, cond in when.items():
            ok, detail = _explain_cond(path, cond, payload)
            paths.append(PathVerdict(path, cond, ok, detail))
            if not ok:
                matched = False
        verdicts.append(
            RuleVerdict(
                index=i,
                name=name,
                action=want_action,
                effect=effect,
                matched=matched,
                paths=paths,
                reason=reason,
            )
        )

    decision = evaluate(policy, action, payload)
    return Explanation(
        action=action,
        payload=payload,
        default=default,
        rules=verdicts,
        decision=decision,
    )


def _explain_cond(path: str, cond: Any, payload: dict) -> tuple[bool, str]:
    v = _matcher()
    actual = v._path_get(payload, path)
    if isinstance(cond, dict) and cond and set(cond).issubset(OPS):
        for op, expected in cond.items():
            if op == "exists":
                present = actual is not v._MISSING
                if present != bool(expected):
                    return False, f"{path}: exists={present}, expected {bool(expected)}"
                return True, f"{path}: exists={present}"
            if actual is v._MISSING:
                if op == "ne":
                    return True, f"{path}: missing != {expected!r}"
                return False, f"{path}: missing"
            if not v._apply(op, actual, expected):
                return False, f"{path}: {actual!r} {op} {expected!r} = false"
            return True, f"{path}: {actual!r} {op} {expected!r} = true"
    if actual is v._MISSING:
        return False, f"{path}: missing"
    if actual != cond:
        return False, f"{path}: {actual!r} == {cond!r} = false"
    return True, f"{path}: {actual!r} == {cond!r} = true"
