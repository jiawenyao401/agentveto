# Why agentveto is Python (and when Rust becomes the answer)

This is a working document, not a manifesto. The decision may change. The point
is to write down what would have to be true for us to revisit it.

## Today: Python is the only honest answer

`agentveto` is at its core a **Python runtime interceptor** for Python code.
The first three things it does only work because Python lets you do them at
import time:

1. **Monkey-patch `openai` / `anthropic` SDKs.** When `agentveto.init()` runs,
   it rewrites the SDK's `ChatCompletion.create` to record the request and
   response. This is a Python affordance; you cannot monkey-patch a compiled
   `.so` the same way. The hook has to be Python.
2. **Decorator on user functions.** `@guard`, `@trace`. The decorator receives
   the actual `inspect.signature(fn)` of the wrapped function so policies can
   address arguments by name. That's Python runtime introspection, not FFI.
3. **`current_run_id`, `current_tracer` as `contextvars.ContextVar`.** Async,
   thread pools, asyncio tasks - one mechanism that already handles all of it.
   Re-implementing it in Rust is its own project.

The hook *has* to be Python. The question is therefore: **what else?**

## What the hot path actually does

Cost of one Veto decision today, measured on the demo:

```
policy lookup  ~ 30 µs
rule match    ~ 80 µs (typical policy, ~10 rules)
record span   ~ 1.5 ms (SQLite insert, WAL mode, local disk)
TOTAL         ~ 1.6 ms per call
```

The bottleneck is **SQLite, not the policy engine.** A Rust policy engine
buys us ~110 µs. The wall-clock win on a 30-step run is about 3 ms. Nobody
will notice.

The thing that *would* be noticed is SQLite. The two real wins:

- **mmap / append-only LSM** instead of SQLite: cuts the per-call overhead
  from 1.5 ms to ~50 µs. Worth doing once we have 1000+ calls per second per
  host.
- **A native replay engine** that can hash-verify and re-run a trace in <10 ms.
  Becomes worth it once we ship signed traces (Prove) and want verification to
  be cheap.

Neither of those requires the *policy engine* to be Rust. They require the
**storage engine** to be Rust, and a Python wrapper around it.

## When Rust becomes worth it

Three thresholds, in order. We cross them in this order, not all at once.

### Threshold 1: 1000+ Veto evaluations per second per host

Today nobody is close. A reasonable 30-step agent run on the demo is 30 Veto
calls per ~3 seconds = 10 calls/sec per host. Even 10× that is fine in Python.

The threshold is **when a single host is processing real production load**
where veto latency starts to be a meaningful slice of total agent latency.
At that point:

- Move `evaluate()` and `match_rule()` to a Rust crate, exposed as a small pyo3
  extension module.
- Keep the decorator, the policy loader, the recorder, and the report in
  Python. The Python surface does not change.
- Effort: ~3 weeks of focused work for one engineer who knows both languages.
- Risk: the pyo3 bridge is its own source of bugs (GIL, refcounts, panic
  propagation across the boundary). Do not start without at least one real
  customer who will use it.

### Threshold 2: we need a portable native binary

Some users want a single static binary they can drop on a server, no Python
runtime. (Usually: regulated environments with locked-down package
allowlists.) If that becomes a real request, we can either:

- Ship a Rust CLI that links a Python interpreter statically and uses it to
  run the existing package. PyOxidizer does this. Effort: 1 week.
- Rewrite the recorder and CLI in Rust, keep the package for Python users.

The second option is **only attractive if we have at least 3 paying customers
asking for the same thing.** Otherwise the Python package is what we ship.

### Threshold 3: someone is paying us to go fast

A real ARR customer with a throughput problem tells us in dollars. Until
then, we are optimizing for time-to-feature, not cycles-per-call.

## What we will NOT do, even if asked

- **Rewrite the SDK hook in Rust.** The hook is the entire value. It must stay
  Python.
- **A pure-Rust `agentveto`.** Two ecosystems to maintain, twice the bugs. If
  someone wants a Rust agent interceptor, they are describing a different
  product.
- **A polyglot Python+TS+Go stack.** Same reason. The product is one thing
  one way. Multi-language SDKs are what a platform company does; we are not
  one.

## If we ever do it, the smallest possible change

1. Identify the three functions with the longest tail on a representative
   workload (today: `_gate` in `veto.py` is the most likely candidate).
2. Move them to a Rust crate named `agentveto-core`. Pure functions, no
   Python imports.
3. Expose via pyo3 as `agentveto._veto_native`.
4. Keep `veto.guard` as the public Python surface; have it call the native
   implementation when available, fall back to pure-Python when not.
5. The 200 tests already in `tests/` become the contract. No test changes.

The total surface area of the rewrite is roughly the size of the `evaluate`
function in `veto.py` today. That's the whole pitch for it.

## TL;DR for the README

> The Python package is the product. A Rust core is a tool we may pick up
> later, not a goal we are working towards today. The line in the sand:
> if someone is paying us in dollars for it, we ship a Rust core. Until
> then, every hour spent on Rust is an hour not spent on the next feature
> a paying user would actually buy.
</content>