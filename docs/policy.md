# Policy language

A policy is a plain Python `dict` (or a JSON file you load from disk).
`@agentveto.guard(policy, action="...")` decorates the tool it protects; the
policy decides, before each invocation, whether the call is allowed, denied,
or must be approved by a human.

## Shape

```python
POLICY = {
    "default": "allow",  # what happens when no rule matches
    "rules": [
        {
            "name": "no-customer-email",  # recorded in the trace
            "action": "send_email",  # exact, "send_*", or "*"
            "effect": "deny",  # allow | deny | ask
            "when": {  # optional: all must hold
                "to": {"endswith": "@external.com"},
            },
            "reason": "External recipients blocked.",  # or {"en": ..., "zh": ...}
        },
        {
            "name": "big-refund",
            "action": "issue_refund",
            "effect": "ask",
            "when": {"amount_usd": {"gt": 250}},
            "reason": "Refunds > $250 need approval.",
        },
    ],
}
```

The grammar:

| Field | Required | Notes |
|---|---|---|
| `default` | no | `allow` (default) or `deny` |
| `rules` | no | an ordered list; first match wins |
| `rule.name` | recommended | unique; surfaces in traces and reports |
| `rule.action` | no, defaults to `*` | exact name, `prefix_*`, or `*` |
| `rule.effect` | yes | `allow`, `deny`, or `ask` |
| `rule.when` | no | a dict of paths to conditions; all must hold |
| `rule.reason` | recommended | plain string or `{lang: text}`; appears in the report |

## Operators

Inside `when`, each value is either a bare value (implicit `eq`) or a dict of
one or more operators:

| Operator | Meaning |
|---|---|
| `eq`, `ne` | equality (and inequality) |
| `gt`, `gte`, `lt`, `lte` | ordered comparison; **silently fails to `false` on incomparable types** (e.g. `string > 0`) |
| `in` | membership in a list |
| `exists` | the path is present (true) or absent (false) |
| `endswith`, `startswith`, `contains` | string operators (both sides must be strings) |
| `len_eq`, `len_gt`, `len_lt` | length comparison; works on strings, lists, dicts |

Paths are dot-separated: `"customer.email"` looks up
`payload["customer"]["email"]`. A missing path fails every operator except
`ne` and `exists`.

## Effects

| Effect | What happens |
|---|---|
| `allow` | the wrapped function runs |
| `deny` | `VetoError` is raised; the wrapped function does **not** run |
| `ask` | if a human is at the keyboard and approves, run; otherwise deny |

`ask` defaults to prompting on `sys.stdin`. In CI, on a server, or in a
cron job there is no human, and the call is denied. This is the
**fail-closed** property; it is intentional. Pass a custom `prompter` to
`guard()` to override (e.g. an in-app approval queue).

## First match wins

Rules are evaluated in order. The first rule whose `action` matches and whose
`when` clauses all hold determines the decision. Order your rules with the
most specific ones first.

```python
"rules": [
    {"action": "send_*", "when": {"to": {"endswith": "@external.com"}}, "effect": "deny"},
    {"action": "send_*", "effect": "ask"},   # everything else needs a human
    {"action": "*", "effect": "allow"},      # everything else is fine
]
```

## Validating and explaining without running

The CLI lets you check a policy and walk one action through it without
running any code:

```bash
agentveto policy show    policy.json
agentveto policy validate policy.json --strict
agentveto policy explain policy.json --action send_email \
    --payload '{"to":"bob@external.com","body":"hi"}'
```

`explain` returns the same shape the runtime decision code returns, so a
"why is this denied" question can be answered by a terminal command in
200 ms instead of reading the source.

## Localised reasons

`reason` may be a string, or a dict of language code to string:

```json
{"reason": {"en": "Refunds > $250 need approval.", "zh": "超过 $250 的退款需要人工审批。"}}
```

`AGENTVETO_LANG` or `LANG` selects which one is shown.

## Loading from a file

```python
import agentveto.policy_io as pio

policy = pio.load_policy("policy.json")


@agentveto.guard(policy, action="send_email")
def send_email(to, subject, body): ...
```

If the policy file is malformed, `load_policy` raises `PolicyError` with a
message you can act on (line / rule index / what went wrong). The runtime
path never falls back to a broken policy; you find out at import time.