package cmd

import (
	"os"
	"strings"
	"testing"

	"github.com/steveyegge/gastown/internal/config"
)

func TestDiscordSeverityColor(t *testing.T) {
	cases := []struct {
		in   string
		want int
	}{
		{config.SeverityCritical, 0xE53935},
		{config.SeverityHigh, 0xFB8C00},
		{config.SeverityMedium, 0xFDD835},
		{config.SeverityLow, 0x43A047},
		{"", 0x9E9E9E},
		{"unknown", 0x9E9E9E},
	}
	for _, c := range cases {
		got := discordSeverityColor(c.in)
		if got != c.want {
			t.Errorf("discordSeverityColor(%q) = %#x, want %#x", c.in, got, c.want)
		}
	}
}

func TestResolveDiscordWebhook_Precedence(t *testing.T) {
	// Save and restore env so parallel tests aren't poisoned.
	prev, hadPrev := lookupEnvSnapshot(t, "DISCORD_WEBHOOK_URL")
	defer restoreEnv(t, "DISCORD_WEBHOOK_URL", prev, hadPrev)

	// 1. explicit flag wins even when env is set
	t.Setenv("DISCORD_WEBHOOK_URL", "https://env.example/x")
	got, err := resolveDiscordWebhook("https://explicit.example/x")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != "https://explicit.example/x" {
		t.Errorf("explicit flag should win, got %q", got)
	}

	// 2. env beats nothing
	got, err = resolveDiscordWebhook("")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != "https://env.example/x" {
		t.Errorf("env var should resolve when no flag, got %q", got)
	}

	// 3. nothing configured => error
	t.Setenv("DISCORD_WEBHOOK_URL", "")
	_, err = resolveDiscordWebhook("")
	if err == nil {
		t.Fatal("expected error when no webhook is configured")
	}
	if !strings.Contains(err.Error(), "no Discord webhook configured") {
		t.Errorf("error should mention configuration, got: %v", err)
	}
}

func TestBuildNotifyEmbed_FreeForm(t *testing.T) {
	embed, err := buildNotifyEmbed("", "Audit fleet", "16 playbooks generated", "low")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got := embed["title"]; got != "Audit fleet" {
		t.Errorf("title = %v, want %q", got, "Audit fleet")
	}
	if got := embed["description"]; got != "16 playbooks generated" {
		t.Errorf("description = %v, want %q", got, "16 playbooks generated")
	}
	if got := embed["color"]; got != discordSeverityColor("low") {
		t.Errorf("color = %v, want %v", got, discordSeverityColor("low"))
	}
}

func TestBuildNotifyEmbed_FreeForm_RequiresContent(t *testing.T) {
	_, err := buildNotifyEmbed("", "", "", "low")
	if err == nil {
		t.Fatal("expected error when neither --title nor --message is provided in free-form mode")
	}
}

func TestBuildNotifyEmbed_DefaultSeverity(t *testing.T) {
	// Empty severity should default to "low" green.
	embed, err := buildNotifyEmbed("", "Update", "ok", "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got := embed["color"]; got != discordSeverityColor("low") {
		t.Errorf("default color should be 'low' (green), got %v", got)
	}
}

func TestBuildNotifyEmbed_CaseInsensitiveSeverity(t *testing.T) {
	embed, err := buildNotifyEmbed("", "Update", "ok", "  CRITICAL  ")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got := embed["color"]; got != discordSeverityColor("critical") {
		t.Errorf("severity should be normalized, got color %v", got)
	}
}

func TestValueOr(t *testing.T) {
	cases := []struct {
		v, fb, want string
	}{
		{"", "fallback", "fallback"},
		{"   ", "fallback", "fallback"},
		{"value", "fallback", "value"},
	}
	for _, c := range cases {
		if got := valueOr(c.v, c.fb); got != c.want {
			t.Errorf("valueOr(%q, %q) = %q, want %q", c.v, c.fb, got, c.want)
		}
	}
}

// lookupEnvSnapshot returns the current value of an env var plus whether it
// was set, so tests that mutate env can restore the exact prior state
// (including the unset/empty distinction).
func lookupEnvSnapshot(t *testing.T, key string) (string, bool) {
	t.Helper()
	return os.LookupEnv(key)
}

func restoreEnv(t *testing.T, key, prev string, hadPrev bool) {
	t.Helper()
	if hadPrev {
		t.Setenv(key, prev)
	} else {
		// t.Setenv handles teardown to whatever the value was at the
		// start of the test, so this branch is effectively a no-op for
		// cleanup. Set explicitly to empty so the running test sees a
		// deterministic "unset-like" value.
		t.Setenv(key, "")
	}
}
