# `gt mcp` — Gas Town as an MCP server

The `gt mcp` family has two purposes:

- **`gt mcp show`** — inspect the per-role MCP allowlist policy that
  Gas Town writes into each role's `.claude/settings.json` during
  `gt hooks sync` (see [`internal/cmd/mcp.go`](../internal/cmd/mcp.go)).
- **`gt mcp serve|stream|tools|claude|cursor|vscode`** — expose `gt`'s
  own safe subcommands as Model Context Protocol (MCP) tools so Hermes
  Agent, Cursor, Claude Desktop, Claude Code, Codex, GitHub Copilot and
  any other MCP-aware client can drive the swarm directly — no bash
  shelling, no flag guessing.

This page documents the second purpose. The first lives in inline help
under `gt mcp show --help`.

The server side is powered by [`github.com/njayp/ophis`](https://github.com/njayp/ophis),
the Cobra → MCP auto-bridge. The integration lives in
[`internal/cmd/mcp_server.go`](../internal/cmd/mcp_server.go) and
attaches ophis's subcommands to the existing `mcpCmd` parent.

## Quick start

```bash
# Register gt with each editor (one-time)
gt mcp cursor enable
gt mcp claude enable
gt mcp vscode enable    # requires GitHub Copilot in Agent Mode

# Restart the editor, then ask the agent something like:
#   "What's ready in Gas Town right now?"  -> calls gt_ready
#   "Show bead bd-abc12"                   -> calls gt_show bd-abc12
#   "Sling bd-xyz99 to crew/dom"           -> calls gt_sling
```

For remote agents (e.g. Hermes Agent on a VPS), stream over HTTP:

```bash
gt mcp stream --host 0.0.0.0 --port 7878
# Then in ~/.hermes/config.yaml:
#   mcp_servers:
#     gastown:
#       url: "http://<host>:7878/mcp"
```

## What's exposed (and what's not)

The MCP surface is **read + coordination only** by design. The selector
allowlist lives in [`internal/cmd/mcp.go`](../internal/cmd/mcp.go).

| Category | Examples | Reason |
|---|---|---|
| ✅ Exposed: read / introspection | `ready`, `show`, `list`, `status`, `info`, `doctor`, `cat`, `log`, `peek`, `audit`, `trail`, `costs`, `metrics`, `feed`, `changelog`, `dashboard`, `memories`, `agents`, `polecat`, `witness`, `mayor`, `deacon`, `dog`, `refinery` | Safe for any agent to call |
| ✅ Exposed: work coordination | `sling`, `unsling`, `assign`, `convoy`, `mountain`, `done`, `mq`, `close`, `release`, `hook`, `handoff`, `resume`, `formula`, `mol`, `synthesis`, `callbacks`, `scheduler` | The job-dispatch surface — the whole point of MCP |
| ✅ Exposed: communication | `mail`, `nudge`, `broadcast`, `escalate`, `dnd` | Agent-to-agent messaging |
| ✅ Exposed: memory + role | `remember`, `forget`, `role` | Persistent knowledge ops |
| ✅ Exposed: beads | `bead`, `beads` | Single source of truth |
| ❌ Excluded: lifecycle / destructive | `down`, `shutdown`, `estop`, `thaw`, `uninstall`, `disable`, `enable`, `up`, `start`, `reaper`, `prune-branches`, `repair`, `cleanup` | Must be human-initiated |
| ❌ Excluded: process / installation | `install`, `git-init`, `init`, `plugin`, `account`, `shell`, `completion` | Setup-only or auth-sensitive |
| ❌ Excluded by ophis safety filters | hidden / deprecated / non-runnable commands; the `mcp` subtree itself | Auto-applied by ophis |

### Flag stripping

Any flag whose name contains `token`, `secret`, `password`, `key`,
`credential`, `api-key`, `auth-token`, or `bearer` is removed from the
tool schema. Persistent (inherited) flags are stripped entirely — a model
should not be able to flip global `gt` behavior through any subcommand.

### Timeouts

Every tool call is wrapped in a 5-minute context timeout (`mcpToolTimeout`
in [`internal/cmd/mcp.go`](../internal/cmd/mcp.go)). A wedged polecat
can't pin the MCP server indefinitely.

## Inspecting the tool list

```bash
gt mcp tools           # writes mcp-tools.json with the full schema
jq '.[].name' mcp-tools.json | head -20
jq 'length' mcp-tools.json
```

Current count: ~289 tools. If your client warns about list size, tighten
`mcpAllowedVerbs` in `mcp.go` (use `ophis.AllowCmds(...)` with full
command paths instead of `AllowCmdsContaining(...)` substrings).

## Adding new MCP-safe commands

1. Confirm the command is **read-safe or coordination-only** (no
   destructive side-effects, no secret-handling).
2. Add the verb substring to `mcpAllowedVerbs` in
   [`internal/cmd/mcp_server.go`](../internal/cmd/mcp_server.go).
3. Rebuild (`make build`), re-export (`gt mcp tools`), confirm the new
   tool appears and the schema looks right.
4. Restart the editor or `gt mcp <editor> enable` again to refresh.

## Removing a command from MCP

Either:

- Remove its verb from `mcpAllowedVerbs`, OR
- Add the full command path to a second `Selector` block with
  `CmdSelector: ophis.ExcludeCmds("gt foo bar")` *before* the allow
  selector (ophis evaluates selectors in order, first match wins).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Tool list empty in editor | Did you restart the editor after `gt mcp <editor> enable`? |
| `gt mcp serve` exits immediately | It speaks stdio JSON-RPC; only run it under an MCP client, not directly. Use `gt mcp tools` to inspect, `gt mcp stream` for HTTP. `gt mcp start` is kept as an alias for back-compat with ophis docs. |
| `gt mcp claude enable` says "not found" | Claude Desktop config lives at `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS). Create Claude Desktop first, then re-run. |
| Warnings in MCP output | `persistentPreRun` skips bd / stale-binary / off-main warnings for the whole `mcp` subtree via `isMCPCommand` in `root.go`. If you see a warning, check whether your subcommand was added with a parent name other than `mcp`. |

## See also

- ophis docs: <https://github.com/njayp/ophis>
- MCP spec: <https://modelcontextprotocol.io>
- Hermes Agent MCP integration: <https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp>
