---
name: contentx-audio-master-loudnorm
description: "Two-pass loudnorm to platform LUFS / true-peak spec; no double-mastering."
trigger: "stage == 'audio_master'"
phase: "audio_master"
derived_from: 4_F2_audio_quality_failures + 14_M1_loudness_target violations
applies_at: audio_master polecat
priority: blocker
---

# Audio master — loudnorm skill

## Why this exists

In the audited runs the same mp4 was produced 3 times — `final_video.mp4`,
`final_video_mastered.mp4`, `final_video_mastered_mastered.mp4`. The second
mastering pass pushed audio to **+0.13 dBTP** (YouTube auto-rejects above -1.0
dBTP). The first pass under-mastered to -19.4 LUFS (4 LUFS under YouTube
target).

This skill is the spec the audio_master polecat consumes.

## Hard spec

Per platform:

| Platform | LUFS target | TP ceiling | LRA |
|---|---:|---:|---:|
| youtube_shorts | -14.0 ± 1.0 | -1.0 dBTP | ≤ 11 |
| tiktok | -16.0 ± 2.0 | -1.0 dBTP | ≤ 11 |
| instagram_reels | -14.0 ± 1.5 | -2.0 dBTP | ≤ 11 |
| youtube_main | -14.0 ± 1.0 | -1.0 dBTP | ≤ 11 |
| linkedin_feed | -16.0 ± 2.0 | -1.0 dBTP | ≤ 11 |

## Two-pass loudnorm (ffmpeg)

```bash
# Pass 1 — measure
ffmpeg -nostats -hide_banner -i INPUT.wav \
  -filter_complex "loudnorm=I=${LUFS}:TP=-1.0:LRA=11:print_format=json" \
  -f null - 2>&1 | python -c "import sys, re, json; m=re.search(r'\{[\s\S]*\}', sys.stdin.read()); print(m.group(0))" > pass1.json

# Pass 2 — apply linear correction with measured values
ffmpeg -y -i INPUT.wav -af "loudnorm=I=${LUFS}:TP=-1.0:LRA=11:linear=true:\
measured_I=$(jq -r .input_i pass1.json):\
measured_TP=$(jq -r .input_tp pass1.json):\
measured_LRA=$(jq -r .input_lra pass1.json):\
measured_thresh=$(jq -r .input_thresh pass1.json):\
offset=$(jq -r .target_offset pass1.json)" OUTPUT.wav
```

## Idempotency guard

Before mastering, the polecat **must** check:

```python
loud = measure_loudness(input_audio)
if abs(loud.input_i - target_lufs) <= tolerance and loud.input_tp <= tp_max:
    # already at spec — skip remaster
    return input_audio
```

This kills the double-mastering bug. The polecat refuses to write
`*_mastered_mastered.*` filenames.

## Refinery binding

This skill is bound to gate `G_audio_passed`. If the post-master measurement
fails any constraint, the gate rejects the MR, the polecat re-runs with the
adjusted target, and only when the measurement passes does the run proceed.
