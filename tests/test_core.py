import asyncio
import json

import pytest

from agentveto import pricing
from agentveto.patch import request_key
from agentveto.report import report as write_report
from agentveto.store import Store
from agentveto.tracer import Tracer


@pytest.fixture
def tracer(tmp_path):
    return Tracer(str(tmp_path / "t.db"), auto_patch=False)


def latest_spans(tracer):
    run = tracer.store.latest_run()
    return tracer.store.get_spans(run["id"])


# ---------------------------------------------------------------- basics

def test_decorator_creates_implicit_run(tracer):
    @tracer.trace
    def add(a, b):
        return a + b

    assert add(2, 3) == 5
    run = tracer.store.latest_run()
    assert run is not None
    assert run["span_count"] == 1
    assert run["status"] == "ok"


def test_decorator_nests_by_call_order(tracer):
    @tracer.trace
    def inner():
        return 1

    @tracer.trace
    def outer():
        return inner() + inner()

    with tracer.start_run("r") as run:
        assert outer() == 2

    spans = tracer.store.get_spans(run.id)
    assert len(spans) == 3
    roots = [s for s in spans if s["parent_id"] is None]
    assert len(roots) == 1
    assert sum(1 for s in spans if s["parent_id"] == roots[0]["id"]) == 2


def test_async_functions_are_traced(tracer):
    @tracer.trace
    async def work():
        await asyncio.sleep(0)
        return "ok"

    assert asyncio.run(work()) == "ok"
    assert tracer.store.latest_run()["span_count"] == 1


def test_disabled_tracer_records_nothing(tmp_path):
    t = Tracer(str(tmp_path / "off.db"), enabled=False, auto_patch=False)

    @t.trace
    def f():
        return 42

    assert f() == 42
    assert t.store.latest_run() is None


# ---------------------------------------------------------------- money

def test_cost_is_computed_from_the_pricing_table(tracer):
    with tracer.start_run("r"):
        with tracer.start_span("llm", kind="llm") as s:
            s.set_model("gpt-4o-mini")
            s.set_usage(1000, 500)

    span = latest_spans(tracer)[0]
    expected = (1000 / 1e6) * 0.15 + (500 / 1e6) * 0.60
    assert span["cost"] == pytest.approx(expected)
    assert span["pricing_known"] == 1


def test_unknown_model_is_not_invented(tracer):
    with tracer.start_span("llm", kind="llm") as s:
        s.set_model("some-future-model-v9")
        s.set_usage(10_000, 10_000)

    span = latest_spans(tracer)[0]
    assert span["pricing_known"] == 0
    assert span["cost"] == 0.0


def test_pricing_matches_dated_model_suffixes():
    assert pricing.resolve("gpt-4o-2024-11-20") == pricing.resolve("gpt-4o")
    assert pricing.resolve("totally-unknown") is None


def test_run_totals_aggregate_child_spans(tracer):
    with tracer.start_run("r") as run:
        with tracer.start_span("a", kind="llm") as s:
            s.set_model("gpt-4o-mini")
            s.set_usage(1000, 1000)
        with tracer.start_span("b", kind="tool"):
            pass

    r = tracer.store.get_run(run.id)
    assert r["span_count"] == 2
    assert r["tokens_in"] == 1000
    assert r["tokens_out"] == 1000
    assert r["total_cost"] > 0


# ---------------------------------------------------------------- failure

def test_errors_are_recorded_and_do_not_swallow_the_exception(tracer):
    with pytest.raises(ValueError):
        with tracer.start_span("boom") as s:
            raise ValueError("payment gateway rejected the refund")

    span = latest_spans(tracer)[0]
    assert span["status"] == "error"
    assert "payment gateway rejected the refund" in span["error"]


def test_failed_run_is_marked(tracer):
    with pytest.raises(RuntimeError):
        with tracer.start_run("r"):
            raise RuntimeError("nope")

    assert tracer.store.latest_run()["status"] == "error"


# ---------------------------------------------------------------- replay

def test_request_key_is_deterministic_and_content_sensitive():
    a = request_key("openai", "gpt-4o", {"messages": [{"role": "user", "content": "hi"}]})
    b = request_key("openai", "gpt-4o", {"messages": [{"role": "user", "content": "hi"}]})
    c = request_key("openai", "gpt-4o", {"messages": [{"role": "user", "content": "ho"}]})
    assert a == b
    assert a != c


def test_request_key_survives_unserialisable_arguments():
    key = request_key("openai", "gpt-4o", {"messages": [], "client": object()})
    assert isinstance(key, str) and len(key) == 64


def test_recordings_round_trip(tmp_path):
    store = Store(str(tmp_path / "rec.db"))
    store.save_recording("k1", "openai", "gpt-4o", {"messages": []}, '{"content":"hi"}')
    rec = store.get_recording("k1")
    assert rec is not None
    assert json.loads(rec["response"])["content"] == "hi"
    assert rec["model"] == "gpt-4o"
    assert store.get_recording("missing") is None


# ---------------------------------------------------------------- report

def test_report_is_written_and_self_contained(tracer, tmp_path):
    with tracer.start_run("support-agent / refund"):
        with tracer.start_span("plan", kind="llm") as s:
            s.set_model("gpt-4o")
            s.set_usage(1200, 300)
            s.set_io(input="what should I do?", output="refund the missing items")
        with tracer.start_span("issue_refund", kind="tool"):
            pass

    out = write_report(store=tracer.store, out=str(tmp_path / "r.html"))
    html = open(out, encoding="utf-8").read()

    assert "tl-data" in html
    assert "<script" in html
    # No external assets: the file must render offline.
    assert 'src="http' not in html
    assert "cdn" not in html.lower()

    blob = html.split('id="tl-data" type="application/json">')[1].split("</script>")[0]
    data = json.loads(blob.replace("<\\/", "</"))
    assert data["run"]["name"] == "support-agent / refund"
    assert len(data["spans"]) == 2


def test_payloads_cannot_break_out_of_the_viewer(tracer, tmp_path):
    with tracer.start_span("hostile", kind="llm") as s:
        s.set_io(input="</script><script>alert(1)</script>")

    out = write_report(store=tracer.store, out=str(tmp_path / "x.html"))
    html = open(out, encoding="utf-8").read()

    assert "alert(1)" in html              # the content is preserved
    assert "<\\/script>" in html           # but it cannot terminate the script block


def test_report_on_empty_database_exits_cleanly(tmp_path):
    store = Store(str(tmp_path / "empty.db"))
    with pytest.raises(SystemExit):
        write_report(store=store, out=str(tmp_path / "n.html"))
