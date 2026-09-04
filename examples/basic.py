"""Three ways to use agentveto, in increasing order of magic.

    AGENTVETO_DB=/tmp/ex.db python examples/basic.py
"""

import agentveto


# 1. Explicit spans. Works for anything, including code that never touches an LLM.
@agentveto.trace(kind="tool")
def lookup_order(order_id: str) -> dict:
    return {"order_id": order_id, "total": 412.50, "shipped": 1, "expected": 3}


# 2. Group work into a named run so the report has a title.
def handle_ticket(ticket: str) -> str:
    with agentveto.start_run("support-agent", meta={"ticket": ticket[:40]}):
        order = lookup_order("A-88213")
        with agentveto.start_span("decide", kind="chain") as span:
            span.set_io(input=order, output="Refund the two items that never shipped.")
            decision = "refund_partial"
        return decision


# 3. If openai or anthropic is installed, init() wraps it and their calls are
#    captured with tokens and cost, with no changes to your call sites.
def with_llm() -> None:
    try:
        from openai import OpenAI
    except ImportError:
        print("openai not installed - skipping the LLM example")
        return

    client = OpenAI(api_key="sk-not-used-for-this-example")
    with agentveto.start_run("llm-example"):
        try:
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Say hello in five words."}],
            )
        except Exception as exc:
            # No valid key here, so the SDK will fail - the span still records
            # the request, the error and the elapsed time, which is the point.
            print(f"LLM call failed as expected without a real key: {type(exc).__name__}")


if __name__ == "__main__":
    agentveto.init()
    handle_ticket("Two of three items never arrived.")
    with_llm()
    out = agentveto.report(out="examples/basic-report.html")
    print(out)
