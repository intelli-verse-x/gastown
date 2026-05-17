// gt mcp serve / stream / tools / claude / cursor / vscode —
// expose Gas Town's safe subcommands as MCP tools so Hermes, Cursor,
// Claude Desktop, Claude Code, Codex, GitHub Copilot and any other
// MCP-aware client can drive the swarm without shelling out.
//
// Powered by github.com/njayp/ophis (Cobra -> MCP auto-bridge, v1.1.4).
// Lives alongside the existing `gt mcp show` allowlist inspector in
// mcp.go — they share the same `mcpCmd` parent so all MCP-related
// surface is under one help tree.
//
// Safety posture for the initial roll-out:
//
//   - Allowlist of read + coordination verbs only. Destructive / process-
//     management surfaces (down, shutdown, estop, uninstall, dolt mutations,
//     plugin, reaper, prune-branches, repair) are NOT exposed. Add them
//     only after audit + a follow-up bead.
//   - All flags containing "token", "secret", "password", "key" are dropped
//     by ExcludeFlags so they can't leak through tool schemas or be set by
//     a remote model.
//   - Inherited persistent flags are NOT exposed (NoFlags); models should
//     not be able to flip global gt behavior through any subcommand.
//   - A 5-minute per-tool timeout is enforced by middleware so a hung
//     subprocess can't pin the MCP server.
//
// Bring-up:
//
//	gt mcp cursor enable   # register with Cursor
//	gt mcp claude enable   # register with Claude Desktop
//	gt mcp vscode enable   # register with VS Code (Copilot agent mode)
//	gt mcp serve           # stdio MCP server (used by enable above)
//	gt mcp stream --host 0.0.0.0 --port 7878  # HTTP MCP server for Hermes
//
// See docs/MCP-SERVER.md for the full operator guide.
package cmd

import (
	"context"
	"os"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	"github.com/njayp/ophis"
)

// mcpAllowedVerbs is the explicit allowlist of substrings that a gt
// command path must contain to be exposed as an MCP tool. Anything not
// matching is hidden from MCP clients.
//
// Grouped roughly by surface area — keep this in sync with
// docs/MCP-SERVER.md.
var mcpAllowedVerbs = []string{
	// read / introspection
	"ready", "show", "list", "status", "info", "doctor",
	"cat", "log", "peek", "audit", "trail", "costs",
	"metrics", "feed", "changelog", "dashboard",
	"memories", "agents", "polecat", "witness",
	"mayor", "deacon", "dog", "refinery",
	// work coordination
	"sling", "unsling", "assign", "convoy", "mountain",
	"done", "mq", "close", "release", "hook", "handoff",
	"resume", "formula", "mol", "synthesis", "callbacks",
	"scheduler",
	// communication
	"mail", "nudge", "broadcast", "escalate", "dnd",
	// memory + role
	"remember", "forget", "role",
	// beads
	"bead", "beads",
}

// mcpDeniedFlagNames are flag-name substrings always stripped from tool
// schemas, regardless of subcommand. Belt + braces over the ophis basic
// safety filter.
var mcpDeniedFlagNames = []string{
	"token", "secret", "password", "key", "credential",
	"api-key", "auth-token", "bearer",
}

// mcpToolTimeout caps the wall-clock cost of any single tool call so a
// stuck subprocess (e.g. a polecat that wedged) can't pin the server.
const mcpToolTimeout = 5 * time.Minute

func init() {
	cfg := &ophis.Config{
		// Nest under the existing `gt mcp` tree (defined in mcp.go).
		// ophis ignores CommandName when we manually attach its
		// subcommands to a parent we already own, but we still set it
		// so any error messages reference the right path.
		CommandName:    "mcp",
		ToolNamePrefix: "gt",

		// Capture PATH so the MCP subprocess can find git, dolt, bd, etc.
		// when launched from Cursor / Claude Desktop / VS Code where the
		// inherited environment is otherwise minimal.
		DefaultEnv: map[string]string{
			"PATH": os.Getenv("PATH"),
		},

		Selectors: []ophis.Selector{{
			CmdSelector:           ophis.AllowCmdsContaining(mcpAllowedVerbs...),
			LocalFlagSelector:     ophis.ExcludeFlags(mcpDeniedFlagNames...),
			InheritedFlagSelector: ophis.NoFlags,
			Middleware:            mcpTimeoutMiddleware,
		}},
	}

	// ophis.Command returns a *cobra.Command named "mcp" with subcommands
	// (start, stream, tools, claude, cursor, vscode). We don't want a
	// second "mcp" parent — pull ophis's subcommands out and attach them
	// directly to the existing mcpCmd (defined in mcp.go).
	//
	// `start` is renamed to `serve` so the verb matches user intent
	// ("serve MCP" reads better than "start MCP") and so it doesn't
	// collide with the existing services-group `gt start` command.
	ophisRoot := ophis.Command(cfg)
	for _, sub := range ophisRoot.Commands() {
		if sub.Name() == "start" {
			sub.Use = "serve"
			sub.Aliases = append(sub.Aliases, "start")
		}
		mcpCmd.AddCommand(sub)
	}
}

// mcpTimeoutMiddleware enforces mcpToolTimeout on every tool call so a
// hung subprocess can't pin the MCP server.
func mcpTimeoutMiddleware(
	ctx context.Context,
	req *mcp.CallToolRequest,
	in ophis.ToolInput,
	next ophis.ExecuteFunc,
) (*mcp.CallToolResult, ophis.ToolOutput, error) {
	ctx, cancel := context.WithTimeout(ctx, mcpToolTimeout)
	defer cancel()
	return next(ctx, req, in)
}
