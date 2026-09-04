# agentveto

**Replay it. Prove it. Veto it.**

Every other tool answers "what did my agent do?". Those tools already exist,
and there are a lot of them. `agentveto` is being built for the harder
question: **what is my agent allowed to do, and can I prove it afterwards?**

Today it does the first part properly. It records every step - prompts, tool
calls, tokens, cost, timing, errors - into a local SQLite file and turns it
into a single HTML file you can open, search, and attach to an incident
report. Then it replays the whole run for free.

No account. No SaaS. No network call. Everything stays on your machine.

```bash
pip install agentveto
```

## 60 seconds

```python
import agentveto

agentveto.init()          # wraps any installed openai / anthropic SDK

@agentveto.trace(kind="tool")
def lookup_order(order_id: str) -> dict:
    return db.orders.find(order_id)

@agentveto.trace
def handle_ticket(ticket: str):
    order = lookup_order(parse_id(ticket))
    return decide(order)

handle_ticket("two of three items never arrived")

agentveto.report()        # writes agentveto-handle-ticket.html
```

Open the HTML file. Every step is on a timeline, clickable, with its input,
output, token count and cost.

**No API key and no LLM?** Run the built-in example:

```bash
python examples/demo.py
```

## What the report looks like

> **TODO:** replace this block with a screenshot of `examples/demo.py` output
> before the first public launch. The GIF in the README is the single biggest
> driver of first-week signups - do not ship without it.

Each row is a step. The bar shows when it ran and how long it took, relative to
the whole run. Click a row to inspect the exact prompt and response. Errors are
red. Replayed LLM calls are marked.

## What it does today

| | |
|---|---|
| **Zero setup** | `init()` and you are done. No project, no token, no dashboard to sign into. |
| **Auto-instrumentation** | Installed `openai` or `anthropic` SDKs are wrapped automatically - tokens and cost captured without touching your call sites. |
| **Explicit spans** | `@trace` or `with start_span(...)` for your own functions and tool calls. Nesting is automatic. |
| **Cost attribution** | Per-step and per-run, using a pricing table you can override. Unknown models are reported as unknown rather than guessed. |
| **Record and replay** | First run records LLM responses. `init(replay=True)` replays them, so a 40-step run is reproducible for free. |
| **Self-contained reports** | One HTML file, no CDN, no build step. Renders offline, six months from now, on a plane. |
| **Nothing leaves your machine** | Traces are written to `./agentveto.db`. There is no server component. |

## Replay: the part that matters

```python
agentveto.init()                       # run once: records every LLM response
agentveto.init(replay=True)            # run again: serves recorded responses
```

The LLM calls come from disk; everything else - routing, tool calls, branching,
your business logic - executes for real. That is what makes an old run
reproducible instead of merely inspectable. It also makes iteration on step 37
free, because you stop paying for steps 1-36.

Streaming responses are traced but not replayable yet.

## How this compares

Recording is a crowded space. Here is the honest map:

| | agentveto | agentblackbox | agentledger (TS) | LangSmith | LangFuse |
|---|---|---|---|---|---|
| Python-native | yes | yes | no | yes | yes |
| Works fully offline | yes | yes | yes | no | no |
| Account required to view a trace | no | no | no | yes | no |
| Single-file report you can email | yes | no | no | no | no |
| Deterministic replay of LLM calls | yes | yes | no | no | no |
| Runtime policy enforcement | on roadmap | no | no | no | no |
| Tamper-evident evidence chain | on roadmap | no | yes | no | no |

Nobody in the Python ecosystem does enforcement yet. Recording tells you what
went wrong; a veto point stops it from going wrong. That is where this is
going.

The other honest part: today this does less than the hosted platforms. No
prompt management, no dataset curation, no hosted dashboards. It does one thing
- tell you exactly what your agent did - with no setup and no data leaving your
machine.

## Roadmap

1. **Replay** (done) - deterministic reproduction of any run, locally, for free.
2. **Prove** (next) - hash-chained, signed traces so a run can be handed to an
   auditor as evidence, not as a screenshot.
3. **Veto** - a policy gate that evaluates a step *before* it executes and can
   block, downgrade, or escalate it. This is the part nobody else has.

## CLI

```bash
agentveto demo                 # example run, no API key needed
agentveto list                 # recorded runs
agentveto report --run <id>    # write a report for a specific run
agentveto serve                # local viewer (pip install 'agentveto[serve]')
```

## Configuration

```python
agentveto.init(
    db="./traces.db",     # or set AGENTVETO_DB
    replay=False,         # serve recorded responses instead of calling the API
    record=True,          # store responses for later replay
    auto_patch=True,      # wrap installed LLM SDKs
)

agentveto.set_pricing({"my-internal-model": (1.0, 4.0)})   # USD per 1M tokens
```

## Status

Early. The data model and the report are stable enough to rely on; the API may
still change before 1.0. Issues and PRs welcome.

## License

Apache 2.0
