# Integrating agentveto with other agent runtimes

> **Read this if you maintain a downstream agent framework and want
> to add an optional one-liner that records + vets + proves runs from
> your code.**
>
> The snippets below are copy-paste-grade. They cover the four
> runtimes we get asked about most. Each one:
>
> - installs with `pip install 'agentveto[serve]'` (FastAPI) — no extra
>   dependency is **required** for the basic record/replay path;
> - calls only public agentveto APIs (`init`, `guard`,
>   `prove.sign`, `prove.export`);
> - works on Python ≥ 3.9 — the same matrix as the package itself;
> - fails open if the user has not installed agentveto (so wrapping is
>   safe to ship behind a feature flag).

If you adapt one of these into a real integration, please open a PR
against this repo so we keep the snippet accurate.

---

## 1. LangChain (`langchain-core` / `langchain`)

```python
# langchain_agentveto.py — drop-in Runnable wrapper
from __future__ import annotations

try:
    import agentveto
    _HAS_VETO = True
except Exception:                       # pragma: no cover
    _HAS_VETO = False

from langchain_core.runnables import Runnable, RunnableConfig


class VetoedRunnable(Runnable):
    """Run a child Runnable under agentveto.guard().

    The policy is resolved from env or a config tag so a parent agent
    can hand a different policy to a child step.
    """

    def __init__(self, inner: Runnable, action: str, policy: dict | None = None):
        self.inner = inner
        self.action = action
        self.policy = policy or {"default": "allow", "rules": []}

    def invoke(self, input, config: RunnableConfig | None = None):
        if not _HAS_VETO:
            return self.inner.invoke(input, config)
        agentveto.init()                 # idempotent
        with agentveto.start_span(
            name=f"langchain.{self.action}",
            attributes={"veto.action": self.action},
        ) as span:
            guarded = agentveto.guard(self.policy, action=self.action)(self.inner.invoke)
            out = guarded(input, config)
            span.set_attribute("veto.decided", "allow")
            return out
```

Usage:

```python
policy = {
  "default": "allow",
  "rules": [{"action": "send_email", "effect": "deny",
             "reason": "outbound email must be approved"}],
}
runnable = VetoedRunnable(my_chain, action="send_email", policy=policy)
```

---

## 2. LangGraph

```python
# langgraph_agentveto.py — node-level instrumentation
import agentveto

agentveto.init()        # once per process

from langgraph.graph import StateGraph
from typing import TypedDict

class S(TypedDict): ...

g = StateGraph(S)

@g.add_node
def tool_node(state: S):
    with agentveto.start_span(name="graph.tool", attributes={"veto.action": "send_email"}) as span:
        # a guard decorator or a check call — pick one
        if not agentveto.check("send_email", payload={"to": state["to"]}).allowed:
            return {"error": "vetoed"}
        return send_email(state["to"], state["subject"], state["body"])

app = g.compile()
```

If you'd rather keep the graph pure, the same `start_span` block
gives you a row in the report without changing control flow.

---

## 3. Dify (tool provider)

Dify tools are plain HTTP. Wrap the body of the tool with
`agentveto.guard`:

```python
# dify_tool_send_email.py — server-side tool provider
import agentveto
from fastapi import FastAPI, Request

app = FastAPI()
agentveto.init(replay=False, record=True)

POLICY = {
    "default": "allow",
    "rules": [
        {"action": "send_email",
         "when": {"to": {"endswith": "@external.com"}},
         "effect": "deny",
         "reason": "external recipients require approval"},
    ],
}

@app.post("/tools/send_email")
async def send_email(req: Request):
    body = await req.json()
    payload = {"to": body["to"], "amount_usd": 0}
    decision = agentveto.check("send_email", payload=payload)
    if not decision.allowed:
        return {"error": "vetoed", "reason": decision.reason}
    # ... real send ...
    return {"ok": True}
```

Dify tools do not need `agentveto` installed on the Dify host; the
provider can run next to the model server.

---

## 4. LiteLLM (proxy route)

LiteLLM is a proxy. Wrap every completion route:

```python
# litellm_agentveto_patch.py — drop into your LiteLLM image
import agentveto
import litellm

agentveto.init()
_orig = litellm.completion

def vetoed_completion(*args, **kwargs):
    # gate by model + estimated cost
    model = kwargs.get("model", args[0] if args else "")
    decision = agentveto.check(
        "llm.call",
        payload={"model": model, "messages": kwargs.get("messages", [])},
    )
    if not decision.allowed:
        raise RuntimeError(f"vetoed: {decision.reason}")
    return _orig(*args, **kwargs)

litellm.completion = vetoed_completion
```

Because the snippet hooks one function, you can ship it as a sidecar
container and keep the upstream LiteLLM image untouched.

---

## Universal: the three things every integration should do

1. **Decide at the boundary, observe downstream.** The `guard` /
   `check` call sits *before* the side-effecting function. The trace
   row sits *around* it.
2. **Default allow, fail closed on unknown rules.** A missing rule =
   `allow`; an unparseable rule = `deny`. We never silently pass
   something the policy author didn't intend.
3. **Optional dependency.** All snippets above degrade to no-ops if
   `import agentveto` fails. A user who doesn't want vetoes doesn't
   pay for them.

---

## How to verify a run end-to-end

```bash
pip install agentveto
# 1) record (in your integration's runtime)
python your_integration_demo.py
# 2) inspect
agentveto list
agentveto report --run <id>
# 3) freeze as evidence
pip install 'agentveto[sign]'
agentveto prove keygen -o ./keys
agentveto prove sign --db agentveto.db --key ./keys/agentveto.key
agentveto prove export --db agentveto.db --run <id> -o incident.evd
# 4) hand to someone who doesn't have your DB
agentveto verify incident.evd
```
