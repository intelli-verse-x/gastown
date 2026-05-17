// Package cmd — bead_pointer.go
//
// Beads is the only source of truth for agent state. mail/nudge are the
// transport for *attention*, never *state*. This file implements the small
// shared machinery that lets `gt mail send --bead <id>` and
// `gt nudge --bead <id>` ship a deterministic pointer to a bead instead of
// re-encoding work plans in prose between agents.
//
// Background: a coordinator (Mayor) routing free-form prose between
// specialized agents is the A2A anti-pattern — context drifts because every
// hop is an open-ended re-interpretation of natural language. Beads is the
// versioned backbone that breaks the drift; the cure is to make the wire
// format point at the bead, not narrate it.
package cmd

import (
	"fmt"
	"strings"

	"github.com/steveyegge/gastown/internal/beads"
	"github.com/steveyegge/gastown/internal/style"
)

// proseLintThreshold is the body size in chars above which we warn that the
// caller is shipping state in prose instead of pointing at a bead. Soft lint
// (non-blocking). Silence per-call with --allow-prose, or restructure the
// call into `bd create … && gt … --bead <id>`.
const proseLintThreshold = 800

// noteLengthCap caps the optional attention note attached to --bead. Notes
// are for "look here, here's a one-liner why" — not for the work itself.
// Longer notes are truncated with a warning to nudge the caller back toward
// putting state in the bead.
const noteLengthCap = 280

// BuildBeadPointerBody renders an attention pointer for a bead. The body
// contains the bead's ID, title, type, priority, and status as they exist
// at the moment the pointer is built — plus a direction to `bd show` for
// the authoritative current state. It deliberately carries no task content
// of its own, so the bead remains the only mutable source of truth.
//
// note (optional) is a short reason for the ping ("ready for review",
// "blocker hit, see comment"). Anything past noteLengthCap is truncated.
func BuildBeadPointerBody(townRoot, beadID, note string) (string, error) {
	id := strings.TrimSpace(beadID)
	if id == "" {
		return "", fmt.Errorf("bead id is empty")
	}

	b := beads.New(townRoot)
	issue, err := b.Show(id)
	if err != nil {
		return "", fmt.Errorf("loading bead %s: %w", id, err)
	}
	if issue == nil {
		return "", fmt.Errorf("bead %s not found", id)
	}

	typ := issue.Type
	if typ == "" {
		typ = "issue"
	}
	status := issue.Status
	if status == "" {
		status = "open"
	}

	header := fmt.Sprintf(
		"📌 bead %s · %q · [%s · %s · %s]",
		issue.ID, issue.Title, typ, priorityLabel(issue.Priority), status,
	)
	footer := fmt.Sprintf(
		"run `bd show %s` for current state — state lives in beads, not in this message.",
		issue.ID,
	)

	note = strings.TrimSpace(note)
	if note == "" {
		return header + "\n\n" + footer, nil
	}
	if len(note) > noteLengthCap {
		style.PrintWarning(
			"--bead note is %d chars (cap %d); truncating. notes are attention, not state — full context goes in the bead",
			len(note), noteLengthCap,
		)
		note = note[:noteLengthCap] + "…"
	}
	return header + "\n\nnote: " + note + "\n\n" + footer, nil
}

// priorityLabel maps the beads numeric priority to the human "Pn" label
// (priorities outside 0-4 are still rendered so future expansion doesn't
// silently break the pointer format).
func priorityLabel(p int) string {
	if p < 0 {
		return fmt.Sprintf("P%d", p)
	}
	return fmt.Sprintf("P%d", p)
}

// WarnIfProseState emits a soft stderr lint when the caller is about to ship
// a large prose body without `--bead` and without `--allow-prose`. The lint
// is the only enforcement on the new architectural rule — there are scripts
// and humans in the wild that legitimately ship one-off prose, so the
// command does not error. callerHint is the command form used in the
// suggestion (e.g. "gt mail send <to>" or "gt nudge <target>").
//
// Returns true when a warning was actually printed (useful for tests).
func WarnIfProseState(body string, hasBead, allowProse bool, callerHint string) bool {
	if hasBead || allowProse {
		return false
	}
	if len(body) < proseLintThreshold {
		return false
	}
	style.PrintWarning(
		"body is %d chars without --bead. mail/nudge should carry attention, not state.\n"+
			"   put the work in a bead, then:\n"+
			"     bd create --title \"…\" --type task   # state lives here\n"+
			"     %s --bead <id> [-m \"short note\"]   # attention pointer\n"+
			"   pass --allow-prose to silence this lint for a one-off prose message",
		len(body), callerHint,
	)
	return true
}
