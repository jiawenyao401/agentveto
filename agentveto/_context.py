"""Context-local state so nested spans work across threads, asyncio tasks and workers.

Everything hangs off contextvars: a task that spawns concurrent LLM calls gets
its own copy of the stack automatically, which is the whole point.
"""

from __future__ import annotations

import contextvars
from typing import Optional, Tuple

current_run_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "agentveto_run_id", default=None
)

# Which Tracer owns the current run. The veto layer needs the concrete
# instance (not the module singleton) so guarded calls land in the same
# store as the run that is actually in progress.
current_tracer: contextvars.ContextVar[Optional[object]] = contextvars.ContextVar(
    "agentveto_tracer", default=None
)

span_stack: contextvars.ContextVar[Tuple[str, ...]] = contextvars.ContextVar(
    "agentveto_span_stack", default=()
)
