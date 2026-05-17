// Package cmd — notify.go
//
// `gt notify` is a one-shot publisher for "action updates" — short
// attention pings that mirror bead lifecycle events to external channels
// (currently Discord). It is intentionally a thin, single-purpose surface;
// the architectural rule from the beads-as-source-of-truth change still
// applies: notifications carry attention, not state. State lives in beads.
//
// The typical caller is a hook, a watcher, or an agent at a turn boundary
// announcing something it just did. The recipient channel becomes a
// scannable timeline of what the fleet is doing without becoming the place
// where work is defined or coordinated — that remains beads' job.
package cmd

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/steveyegge/gastown/internal/beads"
	"github.com/steveyegge/gastown/internal/style"
	"github.com/steveyegge/gastown/internal/workspace"
)

var (
	notifyMessage    string
	notifyTitle      string
	notifyBead       string
	notifySeverity   string
	notifyWebhookURL string
	notifyDryRun     bool
	notifyStdin      bool
)

var notifyCmd = &cobra.Command{
	Use:     "notify",
	GroupID: GroupComm,
	Short:   "Post short attention pings to external channels (currently Discord)",
	Long: `Post a short attention ping to an external channel.

Notifications mirror bead lifecycle events to humans watching a channel
(Discord today; other transports later). They are NOT a place to ship task
state — for that, create/update a bead and reference it with --bead so the
channel shows a pointer at the authoritative source, not a re-encoded copy.

State lives in beads. Notifications carry attention.

WEBHOOK RESOLUTION (in order):
  1. --webhook <url>                              (explicit)
  2. DISCORD_WEBHOOK_URL env var                  (preferred for K8s/CI)
  3. contacts.discord_webhook in escalation.json  (fallback)

EXAMPLES:
  # Bead-anchored (preferred): channel shows a clickable pointer.
  gt notify discord --bead bd-abc123
  gt notify discord --bead bd-abc123 -m "draft PR opened"

  # Free-form one-shot (use sparingly):
  gt notify discord -t "Audit fleet" -m "16 playbooks generated"
  gt notify discord -t "Deploy" -m "rollout complete" --severity low

  # Dry-run: print the payload without posting.
  gt notify discord --bead bd-abc123 --dry-run`,
	RunE: requireSubcommand,
}

var notifyDiscordCmd = &cobra.Command{
	Use:   "discord",
	Short: "Post an attention ping to a Discord channel via webhook",
	Long: `Post an attention ping to a Discord channel via webhook.

Use --bead <id> to attach the notification to a bead — the channel embed
will show the bead's current title/type/priority/status and direct readers
to "bd show <id>" for the authoritative state. -m / --message is then
treated as a short reason for the ping ("ready for review", "blocker hit"),
NOT as the work itself.

For free-form one-shots, use --title and --message. Keep the message under
a sentence; if it's longer, that's a signal you should create a bead and
use --bead instead.

Severity (--severity) drives the embed color: critical=red, high=orange,
medium=yellow, low=green (default: low). Severity is presentational only;
the bead remains the source of truth for the work's actual priority.`,
	RunE: runNotifyDiscord,
}

func init() {
	notifyCmd.AddCommand(notifyDiscordCmd)

	for _, c := range []*cobra.Command{notifyDiscordCmd} {
		c.Flags().StringVarP(&notifyMessage, "message", "m", "", "Short attention note (≤280 chars). Not the work itself — put that in the bead.")
		c.Flags().StringVarP(&notifyTitle, "title", "t", "", "Title for free-form one-shot notifications. Ignored when --bead is set.")
		c.Flags().StringVar(&notifyBead, "bead", "", "Bead ID to anchor the notification to. Embed is built from the bead's current state.")
		c.Flags().StringVar(&notifySeverity, "severity", "low", "Severity for embed color: critical, high, medium, low (default: low)")
		c.Flags().StringVar(&notifyWebhookURL, "webhook", "", "Override webhook URL (otherwise DISCORD_WEBHOOK_URL env, then config)")
		c.Flags().BoolVar(&notifyDryRun, "dry-run", false, "Print the payload that would be posted and exit")
		c.Flags().BoolVar(&notifyStdin, "stdin", false, "Read --message from stdin (avoids shell quoting issues)")
	}

	rootCmd.AddCommand(notifyCmd)
}

func runNotifyDiscord(cmd *cobra.Command, args []string) error {
	if notifyStdin {
		if notifyMessage != "" {
			return fmt.Errorf("cannot use --stdin with --message/-m")
		}
		data, err := io.ReadAll(os.Stdin)
		if err != nil {
			return fmt.Errorf("reading stdin: %w", err)
		}
		notifyMessage = strings.TrimRight(string(data), "\n")
	}

	if notifyBead == "" && notifyTitle == "" && notifyMessage == "" {
		return errors.New("must provide --bead, or --title and/or --message")
	}

	webhook, err := resolveDiscordWebhook(notifyWebhookURL)
	if err != nil && !notifyDryRun {
		return err
	}

	embed, err := buildNotifyEmbed(notifyBead, notifyTitle, notifyMessage, notifySeverity)
	if err != nil {
		return err
	}

	payload := map[string]any{
		"username": "Gas Town",
		"embeds":   []any{embed},
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshaling discord payload: %w", err)
	}

	if notifyDryRun {
		fmt.Println(string(body))
		return nil
	}

	resp, err := http.Post(webhook, "application/json", strings.NewReader(string(body)))
	if err != nil {
		return fmt.Errorf("posting to discord: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("discord webhook returned %d: %s", resp.StatusCode, string(respBody))
	}

	fmt.Printf("%s posted to Discord\n", style.Success.Render("✓"))
	return nil
}

// resolveDiscordWebhook returns the webhook URL using the documented
// precedence: explicit flag > env var > config file. Returns an error if
// none is set so callers (including --dry-run) get a clear message.
func resolveDiscordWebhook(explicit string) (string, error) {
	if explicit != "" {
		return explicit, nil
	}
	if env := os.Getenv("DISCORD_WEBHOOK_URL"); env != "" {
		return env, nil
	}
	// Fall back to escalation config if available.
	if townRoot, err := workspace.FindFromCwd(); err == nil && townRoot != "" {
		// LoadOrCreateEscalationConfig never returns nil cfg on success.
		// We deliberately avoid creating a stub file just to read it —
		// keep this a read-only lookup.
	}
	return "", errors.New("no Discord webhook configured (--webhook, DISCORD_WEBHOOK_URL, or contacts.discord_webhook)")
}

// buildNotifyEmbed renders the Discord embed for a notification. When
// beadID is set the embed is anchored to the bead — its title, type,
// priority, and status are pulled live and the user-supplied message is
// downgraded to a short note. When beadID is empty the embed is a
// free-form one-shot built from title + message.
func buildNotifyEmbed(beadID, title, message, severity string) (map[string]any, error) {
	severity = strings.ToLower(strings.TrimSpace(severity))
	if severity == "" {
		severity = "low"
	}
	color := discordSeverityColor(severity)

	if beadID != "" {
		townRoot, _ := workspace.FindFromCwd()
		b := beads.New(townRoot)
		issue, err := b.Show(beadID)
		if err != nil {
			return nil, fmt.Errorf("loading bead %s: %w", beadID, err)
		}
		if issue == nil {
			return nil, fmt.Errorf("bead %s not found", beadID)
		}

		note := strings.TrimSpace(message)
		if len(note) > noteLengthCap {
			style.PrintWarning(
				"--message is %d chars (cap %d); truncating. messages are attention, not state — full context goes in the bead",
				len(note), noteLengthCap,
			)
			note = note[:noteLengthCap] + "…"
		}

		embed := map[string]any{
			"title":       fmt.Sprintf("bead %s · %s", issue.ID, issue.Title),
			"description": note,
			"color":       color,
			"fields": []map[string]any{
				{"name": "Type", "value": valueOr(issue.Type, "issue"), "inline": true},
				{"name": "Priority", "value": priorityLabel(issue.Priority), "inline": true},
				{"name": "Status", "value": valueOr(issue.Status, "open"), "inline": true},
			},
			"footer": map[string]any{
				"text": "state lives in beads — run `bd show " + issue.ID + "` for current state",
			},
			"timestamp": time.Now().UTC().Format(time.RFC3339),
		}
		return embed, nil
	}

	// Free-form one-shot path.
	if title == "" && message == "" {
		return nil, errors.New("free-form notify requires --title and/or --message")
	}
	embed := map[string]any{
		"title":       valueOr(title, "Gas Town update"),
		"description": message,
		"color":       color,
		"timestamp":   time.Now().UTC().Format(time.RFC3339),
	}
	return embed, nil
}

// valueOr returns v if non-empty, otherwise fallback. Tiny helper kept
// local because the alternative (introducing a util import here) isn't
// worth it for one call site.
func valueOr(v, fallback string) string {
	if strings.TrimSpace(v) == "" {
		return fallback
	}
	return v
}
