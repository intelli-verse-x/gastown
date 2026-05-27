# HMAC Signature Contract — `gates/*.json`

**Algorithm:** HMAC-SHA256
**Key source:** `vault://contentx/cert-key` in production; `CONTENTX_CERT_KEY` env var in dev
**Key rotation:** monthly; previous key kept in `vault://contentx/cert-key/previous` for replay verification of pre-rotation certs
**Encoding:** lower-case hex (matches `^[0-9a-f]{64}$` in `_common.schema.json#/$defs/hmac_sig`)

---

## Canonical payload form

Before computing HMAC the payload is canonicalized:

```python
canonical = json.dumps(
    {k: v for k, v in payload.items() if k != "signature"},
    sort_keys=True,
    separators=(",", ":"),
).encode()
signature = hmac.new(key, canonical, hashlib.sha256).hexdigest()
```

**Rules:**

1. Sort keys lexicographically at every nesting level.
2. Use compact separators `(",", ":")` (no spaces, no trailing newline).
3. The `signature` field is excluded from the canonical form.
4. UTF-8 encoding.
5. The bytes that go into HMAC are exactly the bytes produced by `json.dumps` with these flags — no pretty-printing, no surrogate escapes.
6. Booleans, null, and numbers serialize the JSON-standard way (`true`, `false`, `null`, `42`, `3.14`).

This is the same canonicalization used by `tools/studio_gates/__init__.py::sign()` and `verify()`. Both functions are the source of truth.

---

## What each artifact signs

| Artifact | Path | Payload signed |
|---|---|---|
| Per-gate result | `gates/G{n}.json` | every field of GateResult except `signature` |
| Studio certificate | `certificate.json` | every field except `signature` and `certificate_signature` (the duplicate is an alias) |
| Director sign-off | `approvals/<role>.json` | `{run_id, role, signer, signed_at, output_hash, gate_results_hash}` (the `output_hash` is re-derived from on-disk bytes — any post-signoff mutation invalidates the signature) |
| Chain entry | line in `chain_of_custody.jsonl` | `{seq, prev_hash, at, event}` (hmac field excluded; prev_hash is sha256 of canonical previous entry) |
| Council audit | `council_audits/<rubric_id>_audit.json` | every field except `signature` |

---

## Tamper resistance — what specifically breaks an attacker

| Attack | Detected by | How |
|---|---|---|
| Change a finding in `gates/G6.json` after signing | per-gate signature | recompute HMAC, compare to stored `signature` — mismatch |
| Swap `passed: false → true` on a gate | per-gate signature | same |
| Modify the final mp4 after director sign-off | G13 | `output_hash` is re-derived on every verify; signed value won't match |
| Modify an entry in the chain log | G14 | the entry's HMAC fails AND the next entry's `prev_hash` no longer matches |
| Insert a new entry between two existing entries | G14 | the inserted entry has no valid `prev_hash`, or shifts every subsequent seq |
| Delete a chain entry | G14 | sequence numbers gap; verifier reports `G14_seq_gap` |
| Forge a certificate without the key | studio_cert verify | HMAC will not match without the vault-held key |
| Replace the key in env at verify time | runtime check | post_deploy_verify.C03 round-trip uses the same key; mismatch surfaces |

---

## Trust boundary diagram

```
  ┌──────────────────────────────────────────────────────────────────────┐
  │                  Trust root: vault://contentx/cert-key                │
  │                  (rotated monthly, prior key retained 90d)            │
  └──────────────────────────────────────────────────────────────────────┘
                       │ injected as $CONTENTX_CERT_KEY on host boot
                       ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │  tools/studio_gates/__init__.py    sign(payload), verify(payload)    │
  │  All HMAC operations go through this one function.                   │
  └──────────────────────────────────────────────────────────────────────┘
                       │
        ┌──────────────┼───────────────────┬──────────────────┐
        ▼              ▼                   ▼                  ▼
   gate result    director sign-off   chain entry       certificate
   gates/G*.json  approvals/*.json    chain_of_custody  certificate.json
                                      .jsonl
                       │              │
                       │              │ daily merkle root
                       │              ▼
                       │       chain_of_custody_root.json
                       │       (published to S3, anchored to Dolt)
                       ▼
                7-year retention → s3://contentx-audit-cold/<run_id>/
```

---

## Implementation reference

The canonical reference implementations live in:

- `tools/studio_gates/__init__.py` — `sign()`, `verify()`, `now_utc()`
- `tools/studio_gates/g13_dual_signoff.py` — `sign_for()`, `_output_hash()`, `_gate_results_hash()`
- `tools/studio_gates/g14_chain_of_custody.py` — `append()`, `verify_chain()`, `merkle_root()`

Any new gate or auditor MUST import `sign`/`verify` from `__init__.py`. Do not roll your own.
