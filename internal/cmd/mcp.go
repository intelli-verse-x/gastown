// Package cmd: gt mcp — inspect per-role MCP allowlists.
//
// The `gt mcp` family surfaces the per-role MCP allowlist policy that is
// applied during `gt hooks sync` (see internal/hooks/mcp.go). This is the
// runtime mechanism for the "per-rig MCP allowlists / tool bloat" critique:
// each role's .claude/settings.json gets an explicit enabledMcpjsonServers
// list (with enableAllProjectMcpServers=false), so claude-code refuses to
// load MCP servers outside the allowlist.
//
// Currently exposed:
//   - gt mcp show <target>      effective allowlist for a target
//   - gt mcp show --all         all known targets in the current workspace
//
// Future:
//   - gt mcp allow <target> <server>
//   - gt mcp deny  <target> <server>
//   - gt mcp sync (alias for `gt hooks sync` constrained to MCP fields)
package cmd

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"

	"github.com/spf13/cobra"
	"github.com/steveyegge/gastown/internal/hooks"
	"github.com/steveyegge/gastown/internal/style"
	"github.com/steveyegge/gastown/internal/workspace"
)

var (
	mcpShowAll  bool
	mcpShowJSON bool
)

var mcpCmd = &cobra.Command{
	Use:   "mcp",
	Short: "Inspect per-role MCP allowlist policy",
	Long: `Inspect the per-role MCP allowlist policy that controls which MCP
servers each Gas Town role can load via claude-code.

The policy is applied during 'gt hooks sync' as the enabledMcpjsonServers /
disabledMcpjsonServers / enableAllProjectMcpServers fields in each role's
.claude/settings.json file. Defaults are conservative (firecrawl +
intelli-verse-x for most roles); on-disk overrides at ~/.gt/mcp-overrides/
extend them.`,
	RunE: requireSubcommand,
}

var mcpShowCmd = &cobra.Command{
	Use:   "show [target]",
	Short: "Show effective MCP allowlist for a target",
	Long: `Show the effective MCP allowlist for a target.

A target is a role name (mayor, deacon, crew, polecats, witness, refinery,
auditor, seo, geo, content, qa) or a rig-qualified role (e.g., audits/crew).

Examples:
  gt mcp show crew                 # built-in default for the crew role
  gt mcp show audits/auditor       # rig-qualified target
  gt mcp show --all                # every target discovered in this town
  gt mcp show --all --json         # machine-readable form`,
	Args: cobra.MaximumNArgs(1),
	RunE: runMCPShow,
}

func init() {
	rootCmd.AddCommand(mcpCmd)
	mcpCmd.AddCommand(mcpShowCmd)
	mcpShowCmd.Flags().BoolVar(&mcpShowAll, "all", false, "Show allowlists for every target in the current workspace")
	mcpShowCmd.Flags().BoolVar(&mcpShowJSON, "json", false, "Emit machine-readable JSON")
}

func runMCPShow(cmd *cobra.Command, args []string) error {
	if mcpShowAll {
		return showAllMCPTargets()
	}
	if len(args) == 0 {
		return fmt.Errorf("target required (or use --all); see 'gt mcp show --help'")
	}
	return showOneMCPTarget(args[0])
}

func showOneMCPTarget(target string) error {
	cfg, err := hooks.ComputeExpectedMCP(target)
	if err != nil {
		return fmt.Errorf("computing mcp config: %w", err)
	}
	if mcpShowJSON {
		return emitMCPJSON(map[string]*hooks.MCPConfig{target: cfg})
	}
	printMCPTarget(target, cfg)
	return nil
}

func showAllMCPTargets() error {
	townRoot, err := workspace.FindFromCwdOrError()
	if err != nil {
		return fmt.Errorf("not in a Gas Town workspace: %w", err)
	}
	targets, err := hooks.DiscoverTargets(townRoot)
	if err != nil {
		return fmt.Errorf("discovering targets: %w", err)
	}
	out := map[string]*hooks.MCPConfig{}
	for _, t := range targets {
		cfg, err := hooks.ComputeExpectedMCP(t.Key)
		if err != nil {
			return fmt.Errorf("computing mcp config for %s: %w", t.Key, err)
		}
		out[t.Key] = cfg
	}
	if mcpShowJSON {
		return emitMCPJSON(out)
	}
	for _, t := range targets {
		printMCPTarget(t.Key, out[t.Key])
	}
	return nil
}

func printMCPTarget(key string, cfg *hooks.MCPConfig) {
	if cfg == nil {
		fmt.Printf("%s %s %s\n",
			style.Dim.Render("·"),
			key,
			style.Dim.Render("(no policy — inherits unrestricted)"))
		return
	}
	fmt.Printf("%s %s\n", style.Bold.Render("●"), key)
	if cfg.EnableAll != nil {
		fmt.Printf("  enableAllProjectMcpServers: %v\n", *cfg.EnableAll)
	}
	if len(cfg.Enabled) > 0 {
		fmt.Printf("  allow: %s\n", strings.Join(cfg.Enabled, ", "))
	} else {
		fmt.Printf("  allow: %s\n", style.Dim.Render("(none)"))
	}
	if len(cfg.Disabled) > 0 {
		fmt.Printf("  deny:  %s\n", strings.Join(cfg.Disabled, ", "))
	}
}

func emitMCPJSON(m map[string]*hooks.MCPConfig) error {
	data, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return err
	}
	fmt.Fprintln(os.Stdout, string(data))
	return nil
}

// ensure errors stays referenced (used in test scaffolding for override path)
var _ = errors.Is
