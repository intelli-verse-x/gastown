package hooks

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"testing"
)

func TestDefaultMCPOverrides_KnownRoles(t *testing.T) {
	overrides := DefaultMCPOverrides()
	wantRoles := []string{
		"auditor", "seo", "geo", "content", "qa",
		"crew", "polecats", "witness", "refinery",
		"mayor", "deacon",
	}
	for _, r := range wantRoles {
		cfg, ok := overrides[r]
		if !ok {
			t.Errorf("missing default MCP override for role %q", r)
			continue
		}
		if cfg.EnableAll == nil || *cfg.EnableAll {
			t.Errorf("role %q: EnableAll must default to explicit false (deny-all-then-allow); got %v", r, cfg.EnableAll)
		}
		if len(cfg.Enabled) == 0 {
			t.Errorf("role %q: Enabled list must be non-empty", r)
		}
	}
}

func TestDefaultMCPOverrides_NoForbiddenServers(t *testing.T) {
	// unityMCP and nakama-hiro-satori must never be in a default allowlist;
	// rigs that need them opt in via on-disk overrides only.
	forbidden := map[string]struct{}{
		"unityMCP":           {},
		"nakama-hiro-satori": {},
	}
	for role, cfg := range DefaultMCPOverrides() {
		for _, e := range cfg.Enabled {
			if _, bad := forbidden[e]; bad {
				t.Errorf("role %q has forbidden server %q in default allowlist", role, e)
			}
		}
	}
}

func TestMergeMCP_UnionAndSubtract(t *testing.T) {
	truePtr := true
	base := &MCPConfig{
		EnableAll: &truePtr,
		Enabled:   []string{"firecrawl", "intelli-verse-x"},
	}
	falsePtr := false
	override := &MCPConfig{
		EnableAll: &falsePtr,
		Enabled:   []string{"n8n-mcp"},
		Disabled:  []string{"firecrawl"},
	}
	got := mergeMCP(base, override)

	if got.EnableAll == nil || *got.EnableAll {
		t.Fatalf("EnableAll should be overridden to false, got %v", got.EnableAll)
	}
	wantEnabled := []string{"intelli-verse-x", "n8n-mcp"}
	if !reflect.DeepEqual(got.Enabled, wantEnabled) {
		t.Fatalf("Enabled after merge: want %v, got %v", wantEnabled, got.Enabled)
	}
	if !reflect.DeepEqual(got.Disabled, []string{"firecrawl"}) {
		t.Fatalf("Disabled should be %v, got %v", []string{"firecrawl"}, got.Disabled)
	}
}

func TestMergeMCP_NilInputs(t *testing.T) {
	if mergeMCP(nil, nil) != nil {
		t.Fatal("mergeMCP(nil, nil) should be nil")
	}
	cfg := &MCPConfig{Enabled: []string{"a"}}
	got := mergeMCP(nil, cfg)
	if !reflect.DeepEqual(got.Enabled, []string{"a"}) {
		t.Fatalf("mergeMCP(nil, cfg) should pass through Enabled; got %v", got.Enabled)
	}
}

func TestComputeExpectedMCP_RoleAndRigQualified(t *testing.T) {
	cfg, err := ComputeExpectedMCP("auditor")
	if err != nil {
		t.Fatalf("ComputeExpectedMCP(auditor): %v", err)
	}
	if cfg == nil {
		t.Fatal("ComputeExpectedMCP(auditor) should return policy, got nil")
	}
	if !containsString(cfg.Enabled, "firecrawl") || !containsString(cfg.Enabled, "intelli-verse-x") {
		t.Errorf("auditor default should allow firecrawl + intelli-verse-x; got %v", cfg.Enabled)
	}

	// Rig-qualified target should apply the role default (no rig override on disk).
	cfg2, err := ComputeExpectedMCP("audits/auditor")
	if err != nil {
		t.Fatalf("ComputeExpectedMCP(audits/auditor): %v", err)
	}
	if cfg2 == nil {
		t.Fatal("ComputeExpectedMCP(audits/auditor) should inherit auditor default, got nil")
	}
	if !reflect.DeepEqual(sortedCopy(cfg.Enabled), sortedCopy(cfg2.Enabled)) {
		t.Errorf("rig-qualified target should inherit role default; got %v vs %v", cfg.Enabled, cfg2.Enabled)
	}
}

func TestComputeExpectedMCP_OnDiskOverride(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("GT_HOME", tmp)
	cfg := &MCPConfig{Enabled: []string{"n8n-mcp", "cursor-ide-browser"}}
	if err := SaveMCPOverride("audits/auditor", cfg); err != nil {
		t.Fatalf("SaveMCPOverride: %v", err)
	}
	// File should land at $GT_HOME/.gt/mcp-overrides/audits__auditor.json
	expectedPath := filepath.Join(tmp, ".gt", "mcp-overrides", "audits__auditor.json")
	if _, err := os.Stat(expectedPath); err != nil {
		t.Fatalf("expected override file at %s, stat error: %v", expectedPath, err)
	}

	got, err := ComputeExpectedMCP("audits/auditor")
	if err != nil {
		t.Fatalf("ComputeExpectedMCP: %v", err)
	}
	for _, want := range []string{"firecrawl", "intelli-verse-x", "n8n-mcp", "cursor-ide-browser"} {
		if !containsString(got.Enabled, want) {
			t.Errorf("override should union with role default; missing %q in %v", want, got.Enabled)
		}
	}
}

func TestApplyMCPToSettings(t *testing.T) {
	s := &SettingsJSON{Extra: map[string]json.RawMessage{}}
	falsePtr := false
	cfg := &MCPConfig{
		EnableAll: &falsePtr,
		Enabled:   []string{"firecrawl", "intelli-verse-x"},
		Disabled:  []string{"unityMCP"},
	}
	if !ApplyMCPToSettings(s, cfg) {
		t.Fatal("first apply should report changed=true")
	}
	if got := string(s.Extra["enableAllProjectMcpServers"]); got != "false" {
		t.Errorf("enableAllProjectMcpServers raw: want false, got %q", got)
	}
	var enabled []string
	if err := json.Unmarshal(s.Extra["enabledMcpjsonServers"], &enabled); err != nil {
		t.Fatalf("unmarshal enabledMcpjsonServers: %v", err)
	}
	if !reflect.DeepEqual(enabled, []string{"firecrawl", "intelli-verse-x"}) {
		t.Errorf("enabledMcpjsonServers: want firecrawl,intelli-verse-x; got %v", enabled)
	}
	// Idempotent on second call.
	if ApplyMCPToSettings(s, cfg) {
		t.Error("second apply should be a no-op (changed=false)")
	}
}

func TestHasExpectedMCP(t *testing.T) {
	s := &SettingsJSON{Extra: map[string]json.RawMessage{}}
	falsePtr := false
	cfg := &MCPConfig{
		EnableAll: &falsePtr,
		Enabled:   []string{"firecrawl"},
	}
	if HasExpectedMCP(s, cfg) {
		t.Error("empty settings should not match cfg")
	}
	ApplyMCPToSettings(s, cfg)
	if !HasExpectedMCP(s, cfg) {
		t.Error("after Apply, HasExpectedMCP should be true")
	}
	// Drift: change a value, expect mismatch.
	s.Extra["enabledMcpjsonServers"] = json.RawMessage(`["other"]`)
	if HasExpectedMCP(s, cfg) {
		t.Error("drifted settings should not match cfg")
	}
}

func containsString(xs []string, want string) bool {
	for _, x := range xs {
		if x == want {
			return true
		}
	}
	return false
}

func sortedCopy(in []string) []string {
	out := make([]string, len(in))
	copy(out, in)
	sort.Strings(out)
	return out
}
