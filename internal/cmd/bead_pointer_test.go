package cmd

import (
	"strings"
	"testing"
)

// captureStderr is defined in status_test.go and shared across tests in this
// package; we reuse it here so style.PrintWarning output can be asserted on.

func TestBuildBeadPointerBody_EmptyID(t *testing.T) {
	_, err := BuildBeadPointerBody("", "", "")
	if err == nil {
		t.Fatal("expected error on empty bead id, got nil")
	}
	if !strings.Contains(err.Error(), "empty") {
		t.Errorf("error %q should mention empty id", err.Error())
	}
}

func TestBuildBeadPointerBody_WhitespaceID(t *testing.T) {
	_, err := BuildBeadPointerBody("", "   ", "")
	if err == nil {
		t.Fatal("expected error on whitespace-only bead id, got nil")
	}
}

func TestPriorityLabel(t *testing.T) {
	cases := []struct {
		in   int
		want string
	}{
		{0, "P0"},
		{1, "P1"},
		{2, "P2"},
		{3, "P3"},
		{4, "P4"},
		{7, "P7"},
		{-1, "P-1"},
	}
	for _, c := range cases {
		got := priorityLabel(c.in)
		if got != c.want {
			t.Errorf("priorityLabel(%d) = %q, want %q", c.in, got, c.want)
		}
	}
}

func TestWarnIfProseState_ShortBody_NoWarning(t *testing.T) {
	out := captureStderr(t, func() {
		warned := WarnIfProseState("hi there", false, false, "gt mail send <to>")
		if warned {
			t.Error("short body should not trigger lint")
		}
	})
	if out != "" {
		t.Errorf("unexpected stderr output: %q", out)
	}
}

func TestWarnIfProseState_LongBody_WithBead_NoWarning(t *testing.T) {
	long := strings.Repeat("x", proseLintThreshold+100)
	out := captureStderr(t, func() {
		warned := WarnIfProseState(long, true, false, "gt mail send <to>")
		if warned {
			t.Error("when --bead is set, prose lint must stay silent")
		}
	})
	if out != "" {
		t.Errorf("expected no stderr output when --bead is set, got: %q", out)
	}
}

func TestWarnIfProseState_LongBody_WithAllowProse_NoWarning(t *testing.T) {
	long := strings.Repeat("x", proseLintThreshold+100)
	out := captureStderr(t, func() {
		warned := WarnIfProseState(long, false, true, "gt mail send <to>")
		if warned {
			t.Error("--allow-prose must silence the lint")
		}
	})
	if out != "" {
		t.Errorf("expected no stderr when --allow-prose is set, got: %q", out)
	}
}

func TestWarnIfProseState_LongBody_NoBead_Warns(t *testing.T) {
	long := strings.Repeat("x", proseLintThreshold+50)
	out := captureStderr(t, func() {
		warned := WarnIfProseState(long, false, false, "gt nudge <target>")
		if !warned {
			t.Fatal("long prose body without --bead should trigger lint")
		}
	})
	if !strings.Contains(out, "without --bead") {
		t.Errorf("warning should mention --bead, got: %q", out)
	}
	if !strings.Contains(out, "gt nudge <target>") {
		t.Errorf("warning should echo the caller hint, got: %q", out)
	}
	if !strings.Contains(out, "bd create") {
		t.Errorf("warning should teach the bd create idiom, got: %q", out)
	}
}

func TestWarnIfProseState_AtThreshold_NoWarning(t *testing.T) {
	// At the threshold (not over it), no warning. This guards against
	// off-by-one drift if someone changes the comparison.
	body := strings.Repeat("x", proseLintThreshold-1)
	out := captureStderr(t, func() {
		warned := WarnIfProseState(body, false, false, "gt mail send <to>")
		if warned {
			t.Errorf("body of length %d (< %d) should not warn", len(body), proseLintThreshold)
		}
	})
	if out != "" {
		t.Errorf("unexpected stderr: %q", out)
	}
}
