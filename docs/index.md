# agentveto

**Replay it. Prove it. Veto it.**

Every other tool answers "what did my agent do?". Those tools already exist,
and there are a lot of them. `agentveto` is being built for the harder
question: **what is my agent allowed to do, and can I prove it afterwards?**

No account. No SaaS. No network call. Everything stays on your machine.

```bash
pip install agentveto
```

## Where to go next

- [Policy language](policy.md) - what `@guard(policy, action=...)` accepts,
  what the rules look like, how `when` clauses work.
- [Prove (evidence)](prove.md) - hash-chained, optionally Ed25519-signed runs,
  and portable `.evd` files an auditor can verify offline.
- [MCP server](mcp.md) - expose the policy engine to Claude Code,
  Cursor and other MCP-aware editors.
- [Launch kit](launch.md) - the Show HN / Reddit post draft, comment
  pre-answers, and what *not* to do at launch.
- [Why Python, not Rust](rust-decision.md) - the working document on
  when the cost of a Rust core becomes worth it.

## The shape of the project

- [GitHub repository](https://github.com/jiawenyao401/agentveto)
- [PyPI package](https://pypi.org/project/agentveto/)  *(not published yet)*
- [Issue tracker](https://github.com/jiawenyao401/agentveto/issues)

## Status

Early. The data model and the report are stable enough to rely on; the API
may still change before 1.0. Issues and PRs welcome.

## License

Apache 2.0