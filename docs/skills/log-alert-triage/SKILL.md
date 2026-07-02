---
name: log-alert-triage
description: >
  Triage a Grafana log alert that landed in #gastown-agents-escalations.
  Use when you see an alert message with one of these alertnames:
  ai-error-log-spike, ai-pod-restarting, ai-deployment-unavailable,
  user-backend-error-log-spike, user-backend-pod-restarting,
  user-backend-zeptomail-429-storm, nakama-error-log-spike,
  nakama-multiplayer-pod-restarting, nakama-pod-restarting.
allowed-tools: "Bash(kubectl *), Bash(bd *), Bash(gt *), Bash(gh *), Bash(curl *), Bash(jq *)"
version: "1.0.0"
author: "Gas Town"
---

# Log alert triage — Grafana → Discord → bead

When a Grafana alert lands in `#gastown-agents-escalations`, this skill
takes you from "I see a red message in Discord" to "there is an open
bead with the root cause and the fix, or a witness escalation if I'm
blocked".

The alerts are sourced from
[`intelli-verse-x/intelli-verse-kube-infra/grafana/alerting/`](https://github.com/intelli-verse-x/intelli-verse-kube-infra/tree/main/grafana/alerting)
and each rule's `runbook_url` points back at this file.
The wire format from Grafana includes `alertname`, `team`, `service`,
`namespace`, and `severity` — use those, don't re-derive.

---

## Step 0 — confirm you're the right responder

Each alert carries a `team` label. The default ownership:

| team | first-responder rig |
|---|---|
| `ai` | `intelliverse-ai` crew |
| `user-backend` | `intelliverse-platform` crew |
| `nakama` | `intelliverse-nakama` crew |

If you're not on the right rig and there's no one active on the right
one, claim it anyway — `gt watchman list` to confirm, and proceed.

## Step 1 — file the bead (single source of truth)

Beads is the only authoritative state. Do this **first**, before you
start digging, so concurrent responders don't double-triage.

```bash
# Title format: "<alertname>: <service>" (the Discord embed already shows this)
BD_ID=$(bd create --type bug --priority 1 \
  --title "<alertname>: <service>" \
  --label log-alert \
  --label "team:<team>" \
  --label "service:<service>" \
  | grep -oE 'bd-[a-z0-9]+')
echo "filed: $BD_ID"

bd update "$BD_ID" --status in_progress --claim
```

## Step 2 — gather facts from the cluster

Don't reach for the logs first; the alert annotations and `kubectl get`
tell you whether the issue is "service-down" (rare) or "service-noisy"
(common).

```bash
# --- pod state for the alerting service ---
SVC="<service>"   # e.g. intelliverse-ai-chatbot
kubectl get pods -n aicart -l "app=$SVC" -o wide
kubectl get events -n aicart --sort-by=.lastTimestamp \
  | tail -30 | grep -i "$SVC"

# --- recent crashes? ---
kubectl get pods -n aicart -l "app=$SVC" \
  -o jsonpath='{range .items[*]}{.metadata.name}{"  restarts="}{.status.containerStatuses[0].restartCount}{"  lastState="}{.status.containerStatuses[0].lastState}{"\n"}{end}'
```

Three buckets of cause, in order of likelihood:

1. **Application error spike** — service is up, but logging more
   exceptions per minute than usual. Move to Step 3.
2. **Pod restart loop** — `restartCount` increasing, `lastState`
   shows `OOMKilled` or `Error`. Move to Step 4.
3. **Replicas unavailable** — `kubectl get deploy -n aicart $SVC`
   shows `READY  0/N`. Move to Step 5.

## Step 3 — read the logs for an error spike

```bash
# Reproduce what Grafana saw (last 5m, same regex)
kubectl logs -n aicart -l "app=$SVC" --tail=2000 --since=5m \
  | grep -iE '(\[ERROR\]| ERROR |exception|panic|fatal|traceback|unhandled rejection)' \
  | sort | uniq -c | sort -rn | head -10
```

You're looking for *one* error message that dominates the count.
That's almost always your root cause. Paste the top error into the
bead.

Known recurring patterns:

| Pattern in logs | Cause | Fix |
|---|---|---|
| `ZeptoMail ... Request failed with status code 429` | OTP fallback exceeded ZeptoMail tier | raise tier in ZeptoMail console, or swap primary OTP provider |
| `SignupRewardsService: ... 401` | bad/expired token to rewards API | rotate `SIGNUP_REWARDS_TOKEN` in `secret/intelliverse-user-backend-env` |
| `panic: runtime error: ...` (Nakama) | Lua / Go RPC panicked | the trace identifies the RPC; revert the last Nakama deploy |
| `OpenAI ... 429` or `... 503` (AI chatbot) | upstream LLM provider | check Langfuse for the trace, then LiteLLM routing rules |

## Step 4 — diagnose a pod restart

```bash
# What killed it?
POD=$(kubectl get pods -n aicart -l "app=$SVC" --sort-by=.metadata.creationTimestamp \
       -o jsonpath='{.items[-1].metadata.name}')
kubectl describe pod -n aicart "$POD" | sed -n '/Last State:/,/Events:/p'

# Pre-crash logs
kubectl logs -n aicart "$POD" --previous --tail=200
```

`Reason: OOMKilled` → bump memory in the Helm values or the Deployment
manifest in `intelli-verse-kube-infra/`. `Reason: Error` → read the
previous logs for the actual exit message.

## Step 5 — replicas unavailable

```bash
kubectl describe deploy -n aicart "$SVC" \
  | sed -n '/Conditions:/,/OldReplicaSets/p'
kubectl rollout status deploy/"$SVC" -n aicart --timeout=10s || true
kubectl rollout history deploy/"$SVC" -n aicart
```

Common: image pull failure (ECR auth / wrong tag) or readiness probe
failing. If a recent rollout is the cause:

```bash
kubectl rollout undo deploy/"$SVC" -n aicart
```

— but file a bead with the rolled-back revision so we don't lose the
fix-forward.

## Step 6 — close the loop

```bash
# If you fixed it
bd update "$BD_ID" --status resolved --note "fix: <one-liner> (commit <sha>)"

# If you can't fix it in this session — escalate up the rig
gt escalate --bead "$BD_ID" \
  --reason "<alertname> on <service>: root cause = <one liner>, blocked on <thing you need>"

# Always: post a follow-up to the same Discord channel so the next
# responder doesn't re-do the work
gt nudge --channel gastown-agents-escalations \
  --bead "$BD_ID" -m "claimed + diagnosed; <one-liner state>"
```

## Anti-patterns

- ❌ **Replying in Discord with a wall of logs.** The channel is the
  attention layer; state goes in the bead. A 50-line log paste makes
  the next responder ignore the channel.
- ❌ **Closing the bead because the alert auto-resolved.** Resolved
  alerts often re-fire 30 minutes later. The bead stays in
  `in_progress` until you've identified the cause.
- ❌ **Editing the Grafana rule to silence the alert.** Tune the
  threshold via a PR against
  `intelli-verse-kube-infra/grafana/alerting/rules/`. Direct
  in-UI edits get overwritten next time `apply.sh` runs.

## Related

- Grafana alerting source of truth:
  [`intelli-verse-kube-infra/grafana/alerting/`](https://github.com/intelli-verse-x/intelli-verse-kube-infra/tree/main/grafana/alerting)
- Grafana UI: <https://grafana.intelli-verse-x.ai/alerting/list>
- Discord channel: `#gastown-agents-escalations`
