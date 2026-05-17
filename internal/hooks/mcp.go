// Package hooks: MCP allowlist management.
//
// MCPConfig declares which Claude Code MCP servers a role is permitted to use,
// expressed as enabledMcpjsonServers / disabledMcpjsonServers / enableAllProjectMcpServers
// fields in the role's .claude/settings.json.
//
// Background. Each Gas Town role currently inherits the full union of MCP
// servers configured at the user/workspace level (cursor-ide-browser, n8n-mcp,
// intelliverse-x, unityMCP, nakama-hiro-satori, ...) plus the bd / gt CLI
// surfaces. The Vercel "tool selection" study and Atlan's 2026 agent-design
// guidance both show measurable completion-rate degradation above ~20 tools,
// and reviewers have called this out as a concrete failure mode in the
// gastown deployment ("a polecat boots into well over 20 tools by default").
//
// Per-role allowlists fix this by writing a closed set of enabled MCP servers
// into each role's settings.json during `gt hooks sync`. The defaults are
// intentionally conservative (firecrawl + intelli-verse-x for content/research
// roles; coordinator roles get the wider set). On-disk overrides live next to
// the existing hooks overrides under ~/.gt/mcp-overrides/.
package hooks

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// MCPConfig declares the MCP allowlist policy for a single target.
//
// JSON shape mirrors the Claude Code settings fields exactly:
//
//	{
//	  "enableAllProjectMcpServers": false,
//	  "enabledMcpjsonServers":  ["firecrawl", "intelli-verse-x"],
//	  "disabledMcpjsonServers": ["unityMCP"]
//	}
//
// A nil EnableAll pointer means "leave the field unset" (caller-managed);
// false means "explicit deny-all unless listed in Enabled".
type MCPConfig struct {
	EnableAll *bool    `json:"enableAllProjectMcpServers,omitempty"`
	Enabled   []string `json:"enabledMcpjsonServers,omitempty"`
	Disabled  []string `json:"disabledMcpjsonServers,omitempty"`
}

// DefaultMCPOverrides returns built-in per-role MCP allowlists.
//
// Keys follow the same convention as DefaultOverrides() in this package
// (role name, optionally rig-qualified). On-disk overrides under
// ~/.gt/mcp-overrides/ layer on top of these via the same Merge semantics.
//
// The defaults below encode the user-facing recommendation from the
// "per-rig MCP allowlists / tool bloat" critique:
//
//	role     | mcp_allow
//	---------|------------------------------------
//	auditor  | firecrawl, intelli-verse-x
//	seo      | firecrawl, intelli-verse-x
//	geo      | firecrawl, intelli-verse-x
//	content  | firecrawl, intelli-verse-x, leantime
//	qa       | intelli-verse-x, cursor-ide-browser
//	crew     | firecrawl, intelli-verse-x   (broad default for code-edit roles)
//	polecats | firecrawl, intelli-verse-x
//	witness  | intelli-verse-x              (coordinator, narrow surface)
//	refinery | intelli-verse-x              (gate role, narrow surface)
//	mayor    | firecrawl, intelli-verse-x, n8n-mcp, leantime
//	deacon   | firecrawl, intelli-verse-x, n8n-mcp, leantime
//
// Nothing gets unityMCP or nakama-hiro-satori by default; rigs that need
// those servers must opt in via an on-disk override.
//
// Leantime is wired into the strategic coordinators (mayor, deacon) and
// the content role because those are the surfaces that translate Leantime
// tickets into agent-actionable work. Specialists (seo/geo/auditor/qa)
// stay narrow — they don't need ticket access; their bead is the unit of
// work.
func DefaultMCPOverrides() map[string]*MCPConfig {
	deny := false
	allow := func(servers ...string) *MCPConfig {
		c := &MCPConfig{EnableAll: &deny}
		c.Enabled = append(c.Enabled, servers...)
		return c
	}
	return map[string]*MCPConfig{
		"auditor":  allow("firecrawl", "intelli-verse-x"),
		"seo":      allow("firecrawl", "intelli-verse-x"),
		"geo":      allow("firecrawl", "intelli-verse-x"),
		"content":  allow("firecrawl", "intelli-verse-x", "leantime"),
		"qa":       allow("intelli-verse-x", "cursor-ide-browser"),
		"crew":     allow("firecrawl", "intelli-verse-x"),
		"polecats": allow("firecrawl", "intelli-verse-x"),
		"witness":  allow("intelli-verse-x"),
		"refinery": allow("intelli-verse-x"),
		"mayor":    allow("firecrawl", "intelli-verse-x", "n8n-mcp", "leantime"),
		"deacon":   allow("firecrawl", "intelli-verse-x", "n8n-mcp", "leantime"),
	}
}

// mergeMCP merges an override config into a base config.
// Semantics:
//   - EnableAll: override wins if non-nil.
//   - Enabled / Disabled: union (deduplicated, sorted) so that on-disk
//     overrides extend the built-in allowlist rather than replace it.
//
// To remove a server, add it to Disabled in the override; the final
// effective set is Enabled minus Disabled.
func mergeMCP(base, override *MCPConfig) *MCPConfig {
	if base == nil && override == nil {
		return nil
	}
	out := &MCPConfig{}
	if base != nil {
		out.EnableAll = base.EnableAll
		out.Enabled = append(out.Enabled, base.Enabled...)
		out.Disabled = append(out.Disabled, base.Disabled...)
	}
	if override != nil {
		if override.EnableAll != nil {
			out.EnableAll = override.EnableAll
		}
		out.Enabled = append(out.Enabled, override.Enabled...)
		out.Disabled = append(out.Disabled, override.Disabled...)
	}
	out.Enabled = dedupeSorted(out.Enabled)
	out.Disabled = dedupeSorted(out.Disabled)
	// Subtract Disabled from Enabled so the effective allow set is unambiguous.
	if len(out.Disabled) > 0 && len(out.Enabled) > 0 {
		denied := map[string]struct{}{}
		for _, d := range out.Disabled {
			denied[d] = struct{}{}
		}
		filtered := out.Enabled[:0]
		for _, e := range out.Enabled {
			if _, ok := denied[e]; !ok {
				filtered = append(filtered, e)
			}
		}
		out.Enabled = filtered
	}
	return out
}

func dedupeSorted(in []string) []string {
	if len(in) == 0 {
		return in
	}
	seen := map[string]struct{}{}
	out := in[:0]
	for _, s := range in {
		if _, ok := seen[s]; ok {
			continue
		}
		seen[s] = struct{}{}
		out = append(out, s)
	}
	sort.Strings(out)
	return out
}

// ComputeExpectedMCP returns the effective MCP allowlist for a target, applying
// the same role -> rig/role override resolution as ComputeExpected for hooks.
// Returns nil if neither a built-in nor an on-disk override matches; callers
// should treat nil as "leave settings.json MCP fields untouched."
func ComputeExpectedMCP(target string) (*MCPConfig, error) {
	defaults := DefaultMCPOverrides()
	var result *MCPConfig
	for _, key := range GetApplicableOverrides(target) {
		if def, ok := defaults[key]; ok {
			result = mergeMCP(result, def)
		}
		override, err := LoadMCPOverride(key)
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				continue
			}
			return nil, fmt.Errorf("loading mcp override %q: %w", key, err)
		}
		result = mergeMCP(result, override)
	}
	return result, nil
}

// LoadMCPOverride loads an MCP override for the given target from the gt
// config directories (cascading $GT_HOME/.gt then ~/.gt).
func LoadMCPOverride(target string) (*MCPConfig, error) {
	safe := strings.ReplaceAll(target, "/", "__")
	for _, dir := range gtConfigDirs() {
		path := filepath.Join(dir, "mcp-overrides", safe+".json")
		data, err := os.ReadFile(path)
		if err == nil {
			var cfg MCPConfig
			if err := json.Unmarshal(data, &cfg); err != nil {
				return nil, fmt.Errorf("parsing %s: %w", path, err)
			}
			return &cfg, nil
		}
		if !os.IsNotExist(err) {
			return nil, err
		}
	}
	return nil, os.ErrNotExist
}

// SaveMCPOverride writes an MCP override for the given target to the
// primary .gt config directory.
func SaveMCPOverride(target string, cfg *MCPConfig) error {
	safe := strings.ReplaceAll(target, "/", "__")
	path := filepath.Join(gtPrimaryDir(), "mcp-overrides", safe+".json")
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return fmt.Errorf("creating mcp-overrides directory: %w", err)
	}
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return fmt.Errorf("marshaling mcp config: %w", err)
	}
	data = append(data, '\n')
	if err := os.WriteFile(path, data, 0644); err != nil {
		return fmt.Errorf("writing %s: %w", path, err)
	}
	return nil
}

// ApplyMCPToSettings writes the MCP allowlist fields into a SettingsJSON.
// Returns true if any field was changed relative to the existing Extra map.
//
// Behavior:
//   - cfg == nil → no-op, returns false.
//   - cfg.EnableAll != nil → writes enableAllProjectMcpServers.
//   - cfg.Enabled non-empty → writes enabledMcpjsonServers.
//   - cfg.Disabled non-empty → writes disabledMcpjsonServers.
//
// Existing values in s.Extra are replaced (this is the managed surface).
func ApplyMCPToSettings(s *SettingsJSON, cfg *MCPConfig) bool {
	if cfg == nil || s == nil {
		return false
	}
	if s.Extra == nil {
		s.Extra = make(map[string]json.RawMessage)
	}
	changed := false
	if cfg.EnableAll != nil {
		raw, _ := json.Marshal(*cfg.EnableAll)
		if !rawEqual(s.Extra["enableAllProjectMcpServers"], raw) {
			s.Extra["enableAllProjectMcpServers"] = raw
			changed = true
		}
	}
	if len(cfg.Enabled) > 0 {
		raw, _ := json.Marshal(cfg.Enabled)
		if !rawEqual(s.Extra["enabledMcpjsonServers"], raw) {
			s.Extra["enabledMcpjsonServers"] = raw
			changed = true
		}
	}
	if len(cfg.Disabled) > 0 {
		raw, _ := json.Marshal(cfg.Disabled)
		if !rawEqual(s.Extra["disabledMcpjsonServers"], raw) {
			s.Extra["disabledMcpjsonServers"] = raw
			changed = true
		}
	}
	return changed
}

// HasExpectedMCP reports whether the settings already encode the given
// MCP allowlist exactly. Used by hooks sync to short-circuit no-op writes.
func HasExpectedMCP(s *SettingsJSON, cfg *MCPConfig) bool {
	if cfg == nil {
		return true
	}
	if s == nil || s.Extra == nil {
		return false
	}
	if cfg.EnableAll != nil {
		raw, _ := json.Marshal(*cfg.EnableAll)
		if !rawEqual(s.Extra["enableAllProjectMcpServers"], raw) {
			return false
		}
	}
	if len(cfg.Enabled) > 0 {
		raw, _ := json.Marshal(cfg.Enabled)
		if !rawEqual(s.Extra["enabledMcpjsonServers"], raw) {
			return false
		}
	}
	if len(cfg.Disabled) > 0 {
		raw, _ := json.Marshal(cfg.Disabled)
		if !rawEqual(s.Extra["disabledMcpjsonServers"], raw) {
			return false
		}
	}
	return true
}

func rawEqual(a, b json.RawMessage) bool {
	if len(a) == 0 || len(b) == 0 {
		return len(a) == len(b)
	}
	var av, bv interface{}
	if err := json.Unmarshal(a, &av); err != nil {
		return false
	}
	if err := json.Unmarshal(b, &bv); err != nil {
		return false
	}
	aj, _ := json.Marshal(av)
	bj, _ := json.Marshal(bv)
	return string(aj) == string(bj)
}
