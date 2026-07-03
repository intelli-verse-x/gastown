---
name: contentx-add-captions
description: "Burned-in captions on the mp4 plus a side-car .srt — no exceptions."
trigger: "stage == 'caption_burn'"
phase: "caption_burn"
derived_from: 18_M11_caption_missing findings (all 9 audited runs)
applies_at: caption_burn polecat
priority: blocker
---

# Add captions — caption-burn skill

## Why this exists

`social_publish_auditor.py` flagged **18 distinct M11_caption_missing
findings** across 9 runs — every audited run lacked any caption artifact.
TikTok rejects this as an accessibility fail; YouTube down-ranks; Instagram
shadow-throttles.

## Spec

For every published mp4 the run **must** ship:

1. A side-car `<video_stem>.srt` (Postiz upload) — preferred for YouTube Shorts.
2. A burned-in subtitle track on a *second* mp4 (`<video_stem>_burned.mp4`) for
   TikTok and Instagram (which sometimes muted-autoplay).
3. Subtitle timing precision ≤ 80 ms drift from the actual audio onset.

## Generator

```bash
# 1. Transcribe with whisper.cpp (deterministic; small.en is enough for shorts)
whisper-cpp -m models/ggml-small.en.bin -f $AUDIO -osrt -of $STEM

# 2. Burn into a copy of the video
ffmpeg -y -i $VIDEO \
  -vf "subtitles=$STEM.srt:force_style='FontName=Inter,FontSize=22,Outline=1,Alignment=2,MarginV=80'" \
  -c:a copy ${STEM}_burned.mp4
```

The MarginV=80 keeps subtitles inside the TikTok/Reels lower safe-zone
(300 px from bottom on a 1080×1920 canvas).

## Brand-locked styling

The Honcho persona exposes:
```json
"caption_style": {
  "font": "Inter",
  "size_px": 22,
  "background": "rgba(0,0,0,0.65)",
  "position": "lower-third"
}
```

If the persona is unset (new brand), fall back to the defaults above.

## Refinery binding

`social_publish_auditor.py` checks for both `<stem>.srt` and `<stem>_burned.mp4`
in the same dir as the mp4. Missing either → `M11_caption_missing` → critical →
gate rejects MR.
