"""The tracer: runs, spans, and the decorator people actually call.

Two rules shaped this file:

1. Tracing must never break the host application. Every write is best-effort;
   if SQLite is locked or a payload is unserialisable, we carry on.
2. Zero configuration. Call init() and start decorating - an implicit run is
   created for the outermost decorated call, so a user sees results without
   understanding what a "run" is.
"""

from __future__ import annotations

import functools
import inspect
import time
import traceback
import uuid
from contextlib import contextmanager
from typing import Any

from . import pricing
from ._context import current_run_id, current_tracer, span_stack
from .store import Store


def _now() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:16]


class _NullSpan:
    """Stand-in used when tracing is disabled, so call sites stay unchanged."""

    id = None

    def set_model(self, model): return self
    def set_usage(self, tin=0, tout=0): return self
    def set_io(self, input=None, output=None): return self
    def set_error(self, exc): return self
    def end(self, **kw): return None
    def __enter__(self): return self
    def __exit__(self, *a): return False


class Span:
    def __init__(self, tracer: "Tracer", span_id: str, run_id: str, name: str, kind: str, started_at: float, attributes: dict | None = None):
        self.tracer = tracer
        self.id = span_id
        self.run_id = run_id
        self.name = name
        self.kind = kind
        self.started_at = started_at
        self._attributes = dict(attributes) if attributes else None
        self._model: str | None = None
        self._tokens_in = 0
        self._tokens_out = 0
        self._input: Any = None
        self._output: Any = None
        self._error: str | None = None
        self._replayed = False
        self._ended = False

    # -- mutators -----------------------------------------------------
    def set_attribute(self, key: str, value: Any) -> "Span":
        """Add or replace one attribute before the span is finalised.

        Used by the veto layer so a decision (allow/deny/ask) ends up in the
        same report row as the tool call it guarded.
        """
        if self._attributes is None:
            self._attributes = {}
        self._attributes[key] = value
        return self

    def set_model(self, model: str | None) -> "Span":
        self._model = model
        return self

    def set_usage(self, tokens_in: int = 0, tokens_out: int = 0) -> "Span":
        self._tokens_in = int(tokens_in or 0)
        self._tokens_out = int(tokens_out or 0)
        return self

    def set_io(self, input: Any = None, output: Any = None) -> "Span":
        self._input = input
        self._output = output
        return self

    def set_replayed(self, value: bool = True) -> "Span":
        self._replayed = value
        return self

    def set_error(self, exc: BaseException | str | None) -> "Span":
        if exc is None:
            return self
        self._error = exc if isinstance(exc, str) else "".join(
            traceback.format_exception_only(type(exc), exc)
        ).strip()
        return self

    def fail(self, exc: BaseException) -> "Span":
        self.set_error(exc)
        return self

    # -- lifecycle ----------------------------------------------------
    def end(self, error: BaseException | str | None = None) -> None:
        if self._ended:
            return
        if error is not None:
            self.set_error(error)
        self._ended = True
        ended_at = _now()
        cost, known = pricing.cost(self._model, self._tokens_in, self._tokens_out)
        try:
            self.tracer.store.finish_span(
                self.id,
                ended_at=ended_at,
                duration_ms=(ended_at - self.started_at) * 1000.0,
                status="error" if self._error else "ok",
                model=self._model,
                input=self._input,
                output=self._output,
                tokens_in=self._tokens_in,
                tokens_out=self._tokens_out,
                cost=cost,
                pricing_known=known,
                replayed=self._replayed,
                error=self._error,
                attributes=self._attributes,
            )
        except Exception:  # tracing must never break the caller
            pass

    def __enter__(self) -> "Span":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.end(error=exc)
        return False


class Run:
    def __init__(self, tracer: "Tracer", run_id: str, name: str):
        self.tracer = tracer
        self.id = run_id
        self.name = name

    def span(self, name: str, kind: str = "span", **attributes) -> Any:
        return self.tracer.start_span(name, kind=kind, attributes=attributes or None)


class Tracer:
    def __init__(
        self,
        db: str | None = None,
        *,
        replay: bool = False,
        record: bool = True,
        enabled: bool = True,
        auto_patch: bool = True,
    ):
        self.store = Store(db)
        self.replay = replay
        self.record = record
        self.enabled = enabled
        if enabled and auto_patch:
            self.patch_all()

    # -- instrumentation ----------------------------------------------
    def patch_all(self) -> list[str]:
        from .patch import patch_all

        return patch_all(self)

    # -- runs ----------------------------------------------------------
    @contextmanager
    def start_run(self, name: str = "run", meta: dict | None = None):
        if not self.enabled:
            yield Run(self, "", name)
            return

        run_id = _new_id("run_")
        run_token = current_run_id.set(run_id)
        tr_token = current_tracer.set(self)
        stack_token = span_stack.set(())
        self.store.create_run(run_id, name, _now(), meta)
        status = "ok"
        try:
            yield Run(self, run_id, name)
        except BaseException:
            status = "error"
            raise
        finally:
            try:
                self.store.finish_run(run_id, _now(), status)
            except Exception:
                pass
            span_stack.reset(stack_token)
            current_tracer.reset(tr_token)
            current_run_id.reset(run_token)

    # -- spans ---------------------------------------------------------
    @contextmanager
    def start_span(self, name: str, kind: str = "span", attributes: dict | None = None):
        if not self.enabled:
            yield _NullSpan()
            return

        run_id = current_run_id.get()
        implicit = run_id is None
        run_token = stack_token = tr_token = None
        if implicit:
            run_id = _new_id("run_")
            self.store.create_run(run_id, name, _now())
            run_token = current_run_id.set(run_id)
            tr_token = current_tracer.set(self)
            stack_token = span_stack.set(())

        stack = span_stack.get()
        parent_id = stack[-1] if stack else None
        span_id = _new_id("sp_")
        started = _now()
        self.store.insert_span(span_id, run_id, parent_id, name, kind, started, attributes)
        span = Span(self, span_id, run_id, name, kind, started, attributes)
        span_token = span_stack.set(stack + (span_id,))
        try:
            yield span
        except BaseException as exc:
            span.fail(exc)
            raise
        finally:
            span.end()
            span_stack.reset(span_token)
            if implicit:
                try:
                    self.store.finish_run(run_id, _now(), "error" if span._error else "ok")
                except Exception:
                    pass
                current_run_id.reset(run_token)
                current_tracer.reset(tr_token)
                span_stack.reset(stack_token)

    # -- decorator -----------------------------------------------------
    def trace(self, _fn=None, *, name: str | None = None, kind: str = "span"):
        def decorate(fn):
            span_name = name or getattr(fn, "__qualname__", None) or getattr(fn, "__name__", "call")
            if inspect.iscoroutinefunction(fn):

                @functools.wraps(fn)
                async def async_wrapper(*args, **kwargs):
                    with self.start_span(span_name, kind=kind):
                        return await fn(*args, **kwargs)

                return async_wrapper

            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                with self.start_span(span_name, kind=kind):
                    return fn(*args, **kwargs)

            return wrapper

        if _fn is not None:
            return decorate(_fn)
        return decorate
