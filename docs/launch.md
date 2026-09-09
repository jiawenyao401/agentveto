# Launch Kit — agentveto

> Before this becomes the README / Show HN / Reddit post, every line has to survive one question:
> *"Why would I install this instead of what I already have?"*

## Positioning (use this verbatim across surfaces)

> **agentveto is the runtime veto layer for AI agents.**
> Records every step, replays any run, and can *refuse* to run a step before
> it executes. MIT, zero required dependencies, ships as one Python package.

What it is **not** (say this out loud when asked):

- Not a hosted platform (no account, no server).
- Not a prompt-management / dataset / dashboard product.
- Not a replacement for LangSmith or Helicone — those observe; this one **decides**.

---

## Title candidates — ranked

HN titles that earn the click: ≤ 80 chars, give the benefit, name the mechanism.

| Rank | Title | Why |
|------|-------|-----|
| ★1 | **Show HN: AgentVeto – Runtime veto points for AI agents** | Names the mechanism ("veto"), tells you where it sits ("runtime"), matches the repo name. |
| 2 | Show HN: AgentVeto – A "no" button for your AI agent | Emotional, but soft on mechanism. |
| 3 | Show HN: I built a runtime veto layer for AI agents (MIT, 0 deps) | Bragging the install story, slightly defensive. |
| 4 | Show HN: AgentVeto – Stop your AI agent before it does that | Vague, could be prompt-engineering. |
| 5 | Show HN: agentveto – Replay, prove, and veto AI agent runs | Lists three things; you only get one slot. |

**Recommendation: ship ★1.** Save "replay + prove + veto" for the body.

---

## Show HN body — three lengths

### Short (150 words, default)

> Polished 2026-09-09. The previous draft's numbering (1/3/2) and the
> "nobody else in Python does" line were both counterproductive on HN —
> the first looks like a crammed trick, the second reads as marketing.
> The "5-line story" wrapper was also weak; this version ships a real
> 6-line snippet that you can paste into a terminal.

```
Hi HN — every agent tool tells you what your agent did. agentveto
tells you what it wasn't allowed to do, and stops it before that
happens.

Six lines of Python:

    from agentveto import guard
    POLICY = {"rules": [{"action": "issue_refund",
                         "when": {"amount_usd": {"gt": 250}},
                         "effect": "ask"}]}
    @guard(POLICY, action="issue_refund")
    def issue_refund(order_id, amount_usd): ...

issue_refund("X", 412) raises VetoError, no money moves.
issue_refund("X", 214) runs.

Three layers, plain Python:
  - Veto   — policy gate, fails closed on ask without a human
  - Replay — recorded LLM responses served from disk, free reruns
  - Prove  — hash-chained evidence with optional Ed25519; .evd files
             that verify offline, no db, no SaaS

pip install agentveto. Wraps openai / anthropic automatically. Python
3.9+, zero required deps.

If you've been bitten by an agent firing a real action out of policy,
I'd like to hear the shape of it.
```

**Length**: ~141 words. Hook + code + numbers + ask, four moves.

**Recommended title pairing**: ship this with ★1 ("Runtime veto points").
If ★1 doesn't catch, swap ★1 → ★2 ("A 'no' button") without changing
this body — the title/body axis is mechanism-vs-emotion, the body itself
is unchanged.

### Medium (250 words, the version to actually post)

> Polished 2026-09-09. The previous draft had a real bug — its policy syntax
> (`{"path": ..., "op": ..., "value": ...}`) does not match the actual
> `agentveto.veto` matcher. Anyone who pasted that snippet would have got a
> `PolicyError` on first call. This version uses the real DSL (`{path: {op: v}}`)
> and is the one to ship.

```
Hi HN — every agent tool I know tells you what your agent did. agentveto
is a runtime layer that decides, before the call, what your agent is
allowed to do — and stops the rest.

The pitch in 30 seconds:

    from agentveto import guard
    POLICY = {"rules": [
        {"action": "issue_refund",
         "when": {"amount_usd": {"gt": 250}},
         "effect": "ask"},
        {"action": "send_email",
         "when": {"to": {"endswith": "@external.com"}},
         "effect": "deny"},
    ]}

    @guard(POLICY, action="issue_refund")
    def issue_refund(order_id, amount_usd): ...
    @guard(POLICY, action="send_email")
    def send_email(to, subject, body): ...

issue_refund(88213, 412)            -> VetoError, no charge fires.
issue_refund(12345, 214)            -> runs.
send_email("a@external.com", ...)   -> VetoError, never sent.

What happens to a blocked call? It lands as a veto span in the trace —
same timeline, same single-file HTML report (no CDN, no login, opens on
a plane), marked red so you can audit what was refused and why.

Three layers, all stdlib + an optional `cryptography` for Ed25519:

  Veto    — policy gate, ask-fails-closed when no human is attached
  Replay  — recorded LLM responses served from disk; reruns are free
  Prove   — hash-chained evidence + optional signed `.evd` files that
            verify offline with no db and no SaaS

What is not here, on purpose: no hosted dashboard, no dataset, no
prompt manager. If you already run LangSmith + Helicone and only need
observability, you don't need this. If you've ever had an agent fire a
real action you didn't approve, read the repo.

pip install agentveto. Python 3.9+, zero required deps.

Repo + a 1-page walkthrough: <URL>
```

**Length**: ~245 words. Hook + code + narrative in 4 paragraphs.

**Recommended title pairing**: ship ★1 above with this body. If ★1 doesn't
get traction after 24h on the front page, swap to ★2 ("A 'no' button for
your AI agent") without touching the body — that swaps mechanism for
emotion, useful when the audience is non-devtool.

### Long (500 words, blog post / launch post version)

Use as the GitHub Discussions "Show & tell" or a blog post. It's the same story but
with a worked refund-agent example, a 1-page competitor table, and a roadmap
that's honest about what's next.

(See `docs/blog-v1.md` for the long-form.)

---

## Reddit r/LocalLLaMA / r/MachineLearning versions

**r/LocalLLaMA (friendly, dev-leaning):**

```
Title: agentveto — MIT, zero-dep runtime veto layer for AI agents
(Python, sits next to your local Ollama / vLLM stack)

Body: link + 2-line pitch + "what's the smallest thing I could reject right now"
use case + invite feedback on the policy DSL.
```

**r/MachineLearning (academic-leaning):**

```
Title: [P] Runtime veto points for production LLM agents — MIT

Body: focus on the determinism claim (replay = same hash), the audit story
(hash chain on the roadmap), and a single code example. No marketing words.
Mention the testing approach (deterministic replay is a test fixture).
```

---

## Comment-section prep — questions you will get

Pre-write answers in your head; *do not* paste them as replies. Reply as if you
were just asked the question for the first time.

### "Why not LangSmith?"

LangSmith is observability. It can tell you *after* the fact that your agent
sent 4000 emails by mistake. agentveto is enforcement — it stops the email
from being sent in the first place. They compose: log via LangSmith, block via
agentveto. If your team is OK with *learning from mistakes after they happen*,
LangSmith alone is enough. If you need a CRO to sign a paper saying "this agent
cannot exceed Y," you need a veto layer.

### "Why not agentledger?"

They do signed-trace audit (hash chain + Merkle + Ed25519 + FINRA/EU AI Act
export). Solid project, TypeScript-first. Different point in the chain: they
record approvals, we refuse execution. Their `logApproval()` answers "did a human
OK this?", we answer "may this run?". A regulated team wants both. Cite them
generously; they earned the lane.

### "How do you price it / what's the business model?"

MIT for the package. Paid tier will be a self-hosted control plane with
**offline-signed licenses** (Ed25519, no online check) for teams that want
centralized policy management, audit log retention, and SSO. Solo developer
running a cron agent never needs the paid tier; that's the point.

### "Why not Rust / Go?"

V0's value is auto-patching openai/anthropic at import time — that's a Python
affordance, not portable. The hot path is I/O bound (recording traces, waiting
on LLM responses); Rust buys nothing here. The Veto policy engine is a future
candidate for a Rust rewrite once it's stable and we have a customer whose
throughput matters; today that's premature optimization. (Full reasoning in
`docs/rust-decision.md`.)

### "Does it block prompt injection?"

No, and anyone who says they do is selling something. We can enforce that
*"any tool call that touches `customer_pii` must be approved by a human in the
finance group"* — which means a successful injection still can't exfiltrate.
That's the right shape of guarantee.

### "Why MIT?"

Single maintainer, no investors, no plans to lock people in. If this thing is
worth anything, the lock-in will come from the data you put in it, not the
license. A permissive license gets me more GitHub stars and more good-faith
contributions than any AGPL stunt.

---

## What NOT to do at launch

- Don't post to all 8 subreddits at once. HN first, then the most relevant one
  on day 2, then 1 more on day 5.
- Don't reply to comments within 60 seconds. A 5–10 minute delay reads as
  thought, not auto-reply.
- Don't bury a competitor by name unless they asked. Mention the lane they
  occupy, not their product.
- Don't promise a feature in the launch post that isn't in the code.
- Don't open a Discord / Slack at launch. A Discussions tab on GitHub is enough
  until you have 50+ contributors or 3 customers.
</content>
</invoke>