# Using agentveto from MCP-aware editors

`agentveto` ships an [MCP](https://modelcontextprotocol.io) server which
exposes the policy engine to any MCP-aware client - Claude Code, Cursor,
Continue, Zed, etc. The LLM in your editor can then ask "would this call be
allowed?" before it makes it.

## Install

```bash
pip install 'agentveto[mcp]'
```

This pulls in `mcp<2` (the FastMCP API). The base install has zero deps; MCP
is opt-in so the package doesn't grow for users who never need it.

## Wire it up

In your editor's MCP config (Claude Code's `~/.claude/mcp.json`, Cursor's
settings, etc.):

```json
{
  "mcpServers": {
    "agentveto": {
      "command": "agentveto-mcp",
      "args": ["--policy", "/abs/path/to/your/policy.json"]
    }
  }
}
```

That's it. The server speaks over stdio. No ports, no auth.

## Tools exposed

| Tool | What it does |
|---|---|
| `evaluate_policy(action, payload)` | Returns `{effect, rule, allowed, reason}`. Same call the runtime decorator makes internally. |
| `explain_policy(action, payload)` | Returns every rule's verdict plus the final decision. Use this when writing or debugging a policy. |
| `validate_policy(policy)` | Structural check on a JSON policy. Returns `{valid: bool, error?}` plus the normalised rule count. |
| `load_policy_file(path)` | Hot-swap the active policy without restarting the editor. |

All four tools accept the `policy` argument as a dict, a JSON-encoded string,
or a file path. Without one, `evaluate_policy` and `explain_policy` fall
back to the policy that was loaded at startup (or report "no policy loaded"
if you didn't pass `--policy`).

## Why bother

The point is not "LLM calls the policy engine" - the point is "the LLM can
ask the policy engine *what it would do* before it commits to a tool call,
and rewrite the call if it would be denied." That changes the failure mode:

- **Without MCP:** the LLM calls `send_email`, the gate raises `VetoError`,
  the LLM has to recover from an error mid-run.
- **With MCP:** the LLM asks `evaluate_policy("send_email", {...})`, gets
  back `deny: Marketing email requires a human`, and either rewrites the
  call (`send_in_app_message` instead) or escalates to a human prompt.

That's the difference between "agent that gets caught" and "agent that
doesn't try."

## Custom policy at runtime

The MCP server keeps the loaded policy in memory. To swap it:

```
use the load_policy_file tool with path /etc/agentveto/policy.json
```

The next `evaluate_policy` call will use the new policy. There is no
restart, no signal, no commit ceremony.

## Development loop

While iterating on a policy:

```bash
# 1. draft it
$EDITOR policy.json

# 2. validate it
agentveto policy validate policy.json --strict

# 3. dry-run a representative call
agentveto policy explain policy.json \
    --action send_email \
    --payload '{"to":"bob@external.com","body":"hi"}'

# 4. once the trace looks good, hit reload in your editor
```

This loop runs without the editor running at all. The editor picks up the
new policy on the next call.