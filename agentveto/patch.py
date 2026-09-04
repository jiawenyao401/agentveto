"""Auto-instrumentation for the LLM SDKs, plus record/replay.

Record/replay is the reason this project is worth anything: it makes a run
reproducible. On the first call we store the raw response keyed by a hash of
the request; in replay mode we serve that response instead of hitting the
network. Everything that is not the LLM call (routing, tool calls, branching)
then executes identically, which is what lets you debug step 37 of a 40-step
run without paying for steps 1-36 again.

Only non-streaming calls are recordable in v1. Streaming responses are traced
but never replayed - supporting them properly needs response accumulation and
is a separate piece of work.
"""

from __future__ import annotations

import functools
import hashlib
import json
from typing import Any



def _jsonable(value: Any) -> Any:
    """Drop anything json cannot encode. Never raise."""
    try:
        json.dumps(value, default=str)
        return value
    except Exception:
        pass
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    try:
        json.dumps(value, default=str)
        return value
    except Exception:
        return repr(value)


def request_key(provider: str, model: str | None, payload: dict) -> str:
    body = {"provider": provider, "model": model, "payload": _jsonable(payload)}
    raw = json.dumps(body, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Per-provider adapters
# --------------------------------------------------------------------------

def _openai_messages(payload: dict) -> Any:
    return payload.get("messages") or payload.get("input")


def _openai_result(response: Any) -> tuple[str | None, int, int]:
    text = None
    choices = getattr(response, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        text = getattr(message, "content", None)
    usage = getattr(response, "usage", None)
    tin = int(getattr(usage, "prompt_tokens", 0) or 0)
    tout = int(getattr(usage, "completion_tokens", 0) or 0)
    return text, tin, tout


def _anthropic_result(response: Any) -> tuple[str | None, int, int]:
    text = None
    blocks = getattr(response, "content", None) or []
    parts = []
    for block in blocks:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    if parts:
        text = "".join(parts)
    usage = getattr(response, "usage", None)
    tin = int(getattr(usage, "input_tokens", 0) or 0)
    tout = int(getattr(usage, "output_tokens", 0) or 0)
    return text, tin, tout


def _serialize(response: Any) -> str | None:
    for method in ("model_dump_json", "to_json"):
        fn = getattr(response, method, None)
        if fn:
            try:
                return fn()
            except Exception:
                pass
    return None


def _rebuild(response_cls: Any, blob: str, original: Any):
    for method in ("model_validate_json", "parse_raw"):
        fn = getattr(response_cls, method, None)
        if fn:
            try:
                return fn(blob)
            except Exception:
                pass
    return original


# --------------------------------------------------------------------------
# Wrapper factory
# --------------------------------------------------------------------------

def _wrap(tracer, original, *, provider, label, response_cls, prompt_of, result_of, is_async):
    if getattr(original, "_agentveto_patched", False):
        return None

    def _begin(payload: dict, model: str | None, span_name: str):
        return tracer.start_span(span_name, kind="llm", attributes={"provider": provider})

    if is_async:

        @functools.wraps(original)
        async def async_wrapper(self, *args, **kwargs):
            if not tracer.enabled:
                return await original(self, *args, **kwargs)
            payload = dict(kwargs)
            model = payload.get("model")
            with _begin(payload, model, label) as span:
                stream = bool(kwargs.get("stream"))
                key = request_key(provider, model, payload) if (tracer.record and not stream) else None
                replayed = False
                if tracer.replay and key:
                    rec = tracer.store.get_recording(key)
                    if rec:
                        rebuilt = _rebuild(response_cls, rec["response"], None)
                        if rebuilt is not None:
                            replayed = True
                            response = rebuilt
                if not replayed:
                    try:
                        response = await original(self, *args, **kwargs)
                    except BaseException as exc:
                        span.set_model(model)
                        span.set_io(input=prompt_of(payload))
                        span.fail(exc)
                        raise
                    if tracer.record and key:
                        blob = _serialize(response)
                        if blob:
                            try:
                                tracer.store.save_recording(key, provider, model, payload, blob)
                            except Exception:
                                pass
                text, tin, tout = result_of(response)
                span.set_model(model or getattr(response, "model", None))
                span.set_io(input=prompt_of(payload), output=text)
                span.set_usage(tin, tout)
                span.set_replayed(replayed)
                return response

        async_wrapper._agentveto_patched = True
        return async_wrapper

    @functools.wraps(original)
    def wrapper(self, *args, **kwargs):
        if not tracer.enabled:
            return original(self, *args, **kwargs)
        payload = dict(kwargs)
        model = payload.get("model")
        with _begin(payload, model, label) as span:
            stream = bool(kwargs.get("stream"))
            key = request_key(provider, model, payload) if (tracer.record and not stream) else None
            replayed = False
            if tracer.replay and key:
                rec = tracer.store.get_recording(key)
                if rec:
                    rebuilt = _rebuild(response_cls, rec["response"], None)
                    if rebuilt is not None:
                        replayed = True
                        response = rebuilt
            if not replayed:
                try:
                    response = original(self, *args, **kwargs)
                except BaseException as exc:
                    span.set_model(model)
                    span.set_io(input=prompt_of(payload))
                    span.fail(exc)
                    raise
                if tracer.record and key:
                    blob = _serialize(response)
                    if blob:
                        try:
                            tracer.store.save_recording(key, provider, model, payload, blob)
                        except Exception:
                            pass
            text, tin, tout = result_of(response)
            span.set_model(model or getattr(response, "model", None))
            span.set_io(input=prompt_of(payload), output=text)
            span.set_usage(tin, tout)
            span.set_replayed(replayed)
            return response

    wrapper._agentveto_patched = True
    return wrapper


def _patch_class(tracer, module_name: str, class_name: str, method_name: str, **spec) -> bool:
    try:
        module = __import__(module_name, fromlist=[class_name])
    except Exception:
        return False
    cls = getattr(module, class_name, None)
    if cls is None:
        return False
    original = getattr(cls, method_name, None)
    if original is None:
        return False
    wrapped = _wrap(tracer, original, is_async=class_name.startswith("Async"), **spec)
    if wrapped is None:
        return False
    try:
        setattr(cls, method_name, wrapped)
        return True
    except Exception:
        return False


def patch_all(tracer) -> list[str]:
    """Patch whatever LLM SDKs are installed. Returns the list of patched targets."""
    patched: list[str] = []

    # --- OpenAI chat completions ---
    try:
        from openai.types.chat import ChatCompletion  # noqa: F401
        chat_response_cls = ChatCompletion
    except Exception:
        chat_response_cls = None
    for cls_name in ("Completions", "AsyncCompletions"):
        ok = _patch_class(
            tracer,
            "openai.resources.chat.completions.completions",
            cls_name,
            "create",
            provider="openai",
            label="openai.chat.completions.create",
            response_cls=chat_response_cls,
            prompt_of=_openai_messages,
            result_of=_openai_result,
        )
        if ok:
            patched.append(f"openai.{cls_name}.create")

    # --- OpenAI responses API (newer SDKs) ---
    try:
        from openai.types.responses import Response  # noqa: F401
        responses_cls = Response
    except Exception:
        responses_cls = None
    for cls_name in ("Responses", "AsyncResponses"):
        ok = _patch_class(
            tracer,
            "openai.resources.responses.responses",
            cls_name,
            "create",
            provider="openai",
            label="openai.responses.create",
            response_cls=responses_cls,
            prompt_of=_openai_messages,
            result_of=_openai_result,
        )
        if ok:
            patched.append(f"openai.{cls_name}.create")

    # --- Anthropic messages ---
    try:
        from anthropic.types import Message  # noqa: F401
        anthropic_response_cls = Message
    except Exception:
        anthropic_response_cls = None
    for cls_name in ("Messages", "AsyncMessages"):
        ok = _patch_class(
            tracer,
            "anthropic.resources.messages.messages",
            cls_name,
            "create",
            provider="anthropic",
            label="anthropic.messages.create",
            response_cls=anthropic_response_cls,
            prompt_of=_openai_messages,
            result_of=_anthropic_result,
        )
        if ok:
            patched.append(f"anthropic.{cls_name}.create")

    return patched
