"""Public API.

The whole surface is: init(), @trace, @guard, report(). Everything else is
optional. Nothing here requires a network call, an API key, or an account.
"""

from __future__ import annotations

from . import pricing, prove, veto
from ._version import __version__
from .prove import (
    ProverError,
    Verification,
    export_evidence,
    keygen,
    sign_db,
    verify_db,
    verify_evidence,
    verify_evidence_file,
)
from .report import build_report_data, render_html, report
from .store import Store
from .tracer import Run, Span, Tracer
from .veto import Decision, VetoError, evaluate, guard

__all__ = [
    "__version__",
    "init",
    "get_tracer",
    "trace",
    "start_run",
    "start_span",
    "set_pricing",
    "report",
    "render_html",
    "build_report_data",
    "demo",
    "demo_veto",
    "serve",
    "guard",
    "evaluate",
    "Decision",
    "VetoError",
    "veto",
    "Store",
    "Tracer",
    "Span",
    "Run",
    "keygen",
    "sign_db",
    "export_evidence",
    "verify_evidence",
    "verify_evidence_file",
    "verify_db",
    "Verification",
    "ProverError",
    "prove",
]

_tracer: Tracer | None = None


def init(
    db: str | None = None,
    *,
    replay: bool = False,
    record: bool = True,
    enabled: bool = True,
    auto_patch: bool = True,
) -> Tracer:
    """Start tracing.

    auto_patch=True wraps any installed openai / anthropic SDK, so LLM calls
    are captured without changing call sites.

    replay=True serves recorded LLM responses instead of calling the network,
    which is what makes an old run reproducible.
    """
    global _tracer
    _tracer = Tracer(db, replay=replay, record=record, enabled=enabled, auto_patch=auto_patch)
    return _tracer


def get_tracer() -> Tracer:
    """Return the active tracer, creating one on first use so @trace works standalone."""
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer


def trace(_fn=None, *, name: str | None = None, kind: str = "span"):
    """Works as @trace and as @trace(name="...", kind="tool")."""
    t = get_tracer()
    if _fn is not None:
        return t.trace(_fn)
    return t.trace(name=name, kind=kind)


def start_run(name: str = "run", meta: dict | None = None):
    return get_tracer().start_run(name, meta)


def start_span(name: str, kind: str = "span", attributes: dict | None = None):
    return get_tracer().start_span(name, kind=kind, attributes=attributes)


def set_pricing(table: dict, *, replace: bool = False) -> None:
    pricing.set_pricing(table, replace=replace)


def demo(out: str | None = None, *, open: bool = False) -> str:
    """Generate a realistic example run and write its report. No API key needed."""
    from .demo import demo as _demo

    return _demo(out=out, open=open)


def demo_veto(out: str | None = None, *, open: bool = False) -> str:
    """Generate the runtime-policy example: calls blocked before they run."""
    from .demo import demo_veto as _demo_veto

    return _demo_veto(out=out, open=open)


def serve(db: str | None = None, host: str = "127.0.0.1", port: int = 8420, open: bool = False) -> None:
    """Serve the report viewer locally. Requires: pip install agentveto[serve]"""
    from .serve import serve as _serve

    _serve(db=db, host=host, port=port, open=open)
