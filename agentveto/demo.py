"""An offline example run.

Purpose: someone should be able to see what this does without an API key, an
account, or a network connection. The trace below is synthetic but shaped like
a real incident - a refund agent that plans, calls tools, hits a policy limit,
fails, and escalates. That shape is what the report is for.
"""

from __future__ import annotations

import os
import random
import tempfile
import time

from .report import report
from .tracer import Tracer
from .veto import VetoError, guard

TICKET = (
    "Customer says the order arrived with two items missing and wants a refund "
    "for the full order value (order #A-88213, $412.50). They are threatening a chargeback."
)


def _llm(span_parent, tracer, model, prompt, completion, tin, tout, ms):
    with tracer.start_span(
        "openai.chat.completions.create", kind="llm", attributes={"provider": "openai"}
    ) as span:
        time.sleep(ms / 1000.0)
        span.set_model(model)
        span.set_io(input=prompt, output=completion)
        span.set_usage(tin, tout)


def _tool(tracer, name, args, result, ms=0.0):
    with tracer.start_span(name, kind="tool") as span:
        time.sleep(ms / 1000.0)
        span.set_io(input=args, output=result)


def build_run(tracer: Tracer) -> str:
    random.seed(7)

    with tracer.start_run(
        "support-agent / refund request #A-88213", meta={"demo": True, "env": "example"}
    ) as run:
        with tracer.start_span("agent.handle_ticket", kind="chain") as root:
            root.set_io(input=TICKET)

            _llm(
                root,
                tracer,
                "gpt-4o",
                [
                    {"role": "system", "content": "You are a refund agent. Plan before acting."},
                    {"role": "user", "content": TICKET},
                ],
                "1. Look up order A-88213 to confirm what shipped.\n"
                "2. Check refund policy for partial shipment.\n"
                "3. Issue refund or escalate if above my limit.",
                1284,
                96,
                1180,
            )

            _tool(
                tracer,
                "lookup_order",
                {"order_id": "A-88213"},
                '{"status":"delivered","items":[{"sku":"X-1","qty":1,"price":198.00,'
                '"shipped":true},{"sku":"X-2","qty":1,"price":124.50,"shipped":false},'
                '{"sku":"X-3","qty":1,"price":90.00,"shipped":false}],"total":412.50}',
                140,
            )

            _llm(
                root,
                tracer,
                "gpt-4o",
                [
                    {
                        "role": "user",
                        "content": "Order A-88213: 1 of 3 items shipped. "
                        "Customer demands full refund. What do I do?",
                    }
                ],
                "Two of three items never shipped. Refund the value of the two missing "
                "items: 124.50 + 90.00 = 214.50. Do not refund the delivered item.",
                1710,
                72,
                1420,
            )

            with tracer.start_span("verify_policy", kind="chain") as sub:
                _llm(
                    sub,
                    tracer,
                    "gpt-4o-mini",
                    [
                        {
                            "role": "user",
                            "content": "Is a $214.50 partial refund within "
                            "agent authority for a non-fraud partial shipment?",
                        }
                    ],
                    "Partial shipment refunds under $250 are within agent authority. "
                    "Confirm no prior refund on this order.",
                    640,
                    48,
                    420,
                )
                _tool(
                    tracer,
                    "query_policy_db",
                    {"check": "prior_refund", "order_id": "A-88213"},
                    '{"prior_refunds":0,"within_limit":true}',
                    35,
                )

            # The interesting part: this fails, and it is the whole reason you
            # want a replayable trace rather than logs.
            try:
                with tracer.start_span("issue_refund", kind="tool") as span:
                    span.set_io(input={"order_id": "A-88213", "amount": 214.50, "reason": "partial_shipment"})
                    time.sleep(0.09)
                    raise RuntimeError(
                        "PaymentGateway: refund rejected - amount 214.50 exceeds "
                        "remaining authorisation 180.00 for this payment intent"
                    )
            except RuntimeError:
                pass  # handled by the agent; the span keeps its error state

            _llm(
                root,
                tracer,
                "gpt-4o",
                [
                    {
                        "role": "user",
                        "content": "Refund of 214.50 was rejected: exceeds "
                        "remaining authorisation of 180.00. How do I proceed?",
                    }
                ],
                "Split into two refunds: 180.00 now against the original authorisation, "
                "and escalate the remaining 34.50 to a human for manual review.",
                1890,
                88,
                1610,
            )

            _tool(
                tracer,
                "issue_refund",
                {"order_id": "A-88213", "amount": 180.00, "reason": "partial_shipment_split_1"},
                '{"refund_id":"rf_8812","status":"succeeded","amount":180.00}',
                210,
            )

            _tool(
                tracer,
                "escalate_to_human",
                {
                    "queue": "refund_review",
                    "remaining": 34.50,
                    "note": "Split refund; second half needs manual authorisation",
                },
                '{"ticket":"ESC-4471","assigned_to":"refund_review","eta_hours":4}',
                90,
            )

    return run.id


def demo(out: str | None = None, *, open: bool = False, db: str | None = None) -> str:
    """Record the example run and write its report. Returns the report path."""
    if db is None:
        db = os.path.join(tempfile.gettempdir(), "agentveto-demo.db")
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(db + suffix)
        except OSError:
            pass

    tracer = Tracer(db, auto_patch=False)
    run_id = build_run(tracer)
    path = report(run_id, out=out, store=tracer.store)
    if open:
        import webbrowser

        webbrowser.open("file://" + os.path.abspath(path))
    return path


# =====================================================================
# Veto layer demo: policy gates evaluated *before* a call goes out.
# The shape of the story: same refund agent, but now the runtime refuses
# calls that would have been a problem - and each refusal is on the record.
# =====================================================================

REFUND_POLICY = {
    "default": "allow",
    "rules": [
        {
            "name": "no-customer-email",
            "action": "send_email",
            "effect": "deny",
            "reason": "Outbound email to a customer requires a human in the loop.",
        },
        {
            "name": "refund-needs-approval-over-250",
            "action": "issue_refund",
            "effect": "ask",
            "when": {"amount_usd": {"gt": 250}},
            "reason": "Refunds over $250 require a human approver.",
        },
        {
            "name": "no-full-pii-export",
            "action": "export_pii",
            "effect": "deny",
            "when": {"scope": {"eq": "full"}},
            "reason": "Full-scope PII export is only allowed for a verified data-subject request.",
        },
    ],
}


def _refund_impl(order_id: str, amount_usd: float, reason: str) -> dict:
    return {
        "refund_id": "rf_" + str(random.randint(10000, 99999)),
        "order_id": order_id,
        "amount_usd": amount_usd,
        "reason": reason,
        "status": "succeeded",
    }


def _email_impl(to: str, subject: str, body: str) -> dict:
    return {"status": "sent", "to": to, "subject": subject}


def _export_impl(scope: str, user_id: str) -> dict:
    return {"rows": 0, "scope": scope, "user_id": user_id}


def _headless(decision, payload) -> bool:
    """No human at the keyboard: an 'ask' rule fails closed. Keeps the demo
    deterministic whether it runs in CI, in a pipe, or on a terminal."""
    return False


# The same three tools, now behind the policy gate.
guarded_refund = guard(REFUND_POLICY, action="issue_refund", prompter=_headless)(_refund_impl)
guarded_email = guard(REFUND_POLICY, action="send_email", prompter=_headless)(_email_impl)
guarded_export = guard(REFUND_POLICY, action="export_pii", prompter=_headless)(_export_impl)

VETO_TICKET = (
    "Customer #8841 wants the full $412.50 refunded to their card and asks us to "
    "email a confirmation. Agent suspects fraud, wants to export the customer's "
    "full profile to review it."
)


def build_veto_run(tracer: Tracer) -> str:
    random.seed(11)

    with tracer.start_run(
        "veto demo / refund agent under policy", meta={"demo": True, "env": "example", "layer": "veto"}
    ) as run:
        with tracer.start_span("agent.handle_refund", kind="chain") as root:
            root.set_io(input=VETO_TICKET)

            _llm(
                root,
                tracer,
                "gpt-4o",
                [
                    {"role": "system", "content": "You are a refund agent with a policy gate."},
                    {"role": "user", "content": VETO_TICKET},
                ],
                "1. Refund the two missing items ($214.50) - within my authority.\n"
                "2. Email the customer a confirmation.\n"
                "3. Export the customer profile to check for fraud.",
                1502,
                118,
                1330,
            )

            # 1) A $214.50 partial refund: under the $250 ask-line. Allowed.
            res = guarded_refund(order_id="A-88213", amount_usd=214.50, reason="partial_shipment")

            # 2) The agent emails the customer. The policy denies it before send.
            try:
                guarded_email(
                    to="customer@example.com",
                    subject="Your refund",
                    body="Good news, your refund of $214.50 is on its way...",
                )
            except VetoError as exc:
                # The agent sees a VetoError and has to take another path.
                root.set_io(output=f"email blocked: {exc}")

            _llm(
                root,
                tracer,
                "gpt-4o-mini",
                [
                    {
                        "role": "user",
                        "content": "Emailing the customer was blocked by "
                        "policy (no-customer-email). What is the fallback?",
                    }
                ],
                "Do not override the policy. Mark the confirmation as pending "
                "for the human queue instead of emailing directly.",
                812,
                61,
                480,
            )

            # 3) Full refund attempt for the whole $412.50: crosses the ask-line.
            #    No human at the keyboard in this run, so it fails closed.
            try:
                guarded_refund(order_id="A-88213", amount_usd=412.50, reason="full_order_refund")
            except VetoError as exc:
                root.set_io(output=f"refund blocked: {exc}")

            # 4) Fraud check by exporting the full PII profile: denied outright.
            try:
                guarded_export(scope="full", user_id="8841")
            except VetoError as exc:
                root.set_io(output=f"export blocked: {exc}")

            _llm(
                root,
                tracer,
                "gpt-4o",
                [
                    {
                        "role": "user",
                        "content": "Three actions were blocked by policy. "
                        "How do we proceed with the customer?",
                    }
                ],
                "Escalate to refund_review with the blocked actions attached. "
                "A human approves the $412.50 refund, sends the email, and runs "
                "the fraud review on a need-to-know scope.",
                1718,
                89,
                1205,
            )

            _tool(
                tracer,
                "escalate_to_human",
                {
                    "queue": "refund_review",
                    "ticket": "ESC-8841",
                    "blocked": ["send_email", "issue_refund:412.50", "export_pii:full"],
                },
                '{"ticket":"ESC-8841","assigned_to":"refund_review","eta_hours":4}',
                60,
            )

    return run.id


def demo_veto(out: str | None = None, *, open: bool = False, db: str | None = None) -> str:
    """Record the veto-layer example run and write its report."""
    if db is None:
        db = os.path.join(tempfile.gettempdir(), "agentveto-veto-demo.db")
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(db + suffix)
        except OSError:
            pass

    tracer = Tracer(db, auto_patch=False)
    run_id = build_veto_run(tracer)
    path = report(run_id, out=out, store=tracer.store)
    if open:
        import webbrowser

        webbrowser.open("file://" + os.path.abspath(path))
    return path
