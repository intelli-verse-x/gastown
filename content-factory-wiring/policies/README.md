# policies/ — Human decisions required before AA tier

The four files in this folder encode the policy decisions that are intentionally
held outside code review. Each has a named owner; each maps directly to a tier
gate; each requires a human signoff before the first content at tier ≥ AA ships.

| File | Owner | Decision | Status if empty |
|---|---|---|---|
| `tier_floors.toml` | Head of Content | What "indie/AA/AAA" mean in score terms | Cannot tier above `internal` |
| `retention_policy.toml` | Legal | Storage duration by jurisdiction | S3 cold-storage defaults to 7y; DE/FR runs blocked |
| `director_assignments.toml` | Brand owner | Who's CD + TD per brand | Cannot tier above `indie` |
| `override_policy.toml` | VP Eng | Who can override, what counts against SLO | Overrides return 403 |

## Loading order

Refinery (and `gt refinery reload`) reads in this order:

```
configs/refinery.toml                  # base global gate config
configs/refinery_viral_shorts.toml     # pipeline overlay (if loaded)
policies/tier_floors.toml              # tier semantics
policies/retention_policy.toml         # S3 lifecycle inputs
policies/director_assignments.toml     # signer identity
policies/override_policy.toml          # break-glass rules
```

Later files override earlier ones for the same key.

## How to fill these in

1. **Open a PR** modifying only the file you need.
2. **Reviewer must be** the named owner from the table above.
3. On merge, refinery picks up the change via the on-host cron job
   (`hermes/cron_jobs.yaml::reload_policies`) which `gt refinery reload`s every 5 min.
4. The change is appended to `chain_of_custody.jsonl/policy_change` on every host.

## What "empty" means

When a required field is `""`, the auditor / refinery rejects the run with
`PolicyMissingError: <field> required for tier=<tier>`. This is by design —
unfilled policy is treated as "not yet authorized", not "permissive default".
