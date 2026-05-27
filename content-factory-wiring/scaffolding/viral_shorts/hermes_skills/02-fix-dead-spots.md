---
name: contentx-fix-dead-spots
description: "Eliminate static segments > 3 s before they cost retention."
trigger: "pipeline.kind in ['viral_shorts', 'short_video']"
phase: "director_brief"
derived_from: 2_council_directives ("Fix dead spot 0:08-0:12")
applies_at: director
priority: medium
---

# Fix dead spots — director-brief skill

## Pattern observed

`council_audits/video_audit.json` directive across 2+ runs:

> Fix dead spot 0:08-0:12: 4s of static text overlay with no visual movement.

This kills 30 s retention by ~10 pp. Council catches it post-hoc; this skill
catches it pre-hoc.

## Director constraint

For any scene whose **wall-time duration ≥ 3 s**, the director brief must include
at least one of:

- a camera motion directive (`push_in`, `pull_back`, `pan_left`, `parallax`)
- a character motion directive (`gesture`, `walk`, `head_turn`)
- a content overlay change (text/sticker enters or exits the frame)
- a cut to a different angle of the same subject

Static frame budget per 15 s clip: **≤ 1.5 s total**, never contiguous > 1 s.

## Auto-injection rule

If a brief has consecutive scene blocks totaling > 3 s without any motion
field, the director polecat **must** inject a `motion_hint: parallax_drift`
field into the brief before passing to `video_generation`.

## Council reciprocal check

`council/video_audit` runs the dead-spot detector on the final mp4:
```
ffprobe -f lavfi -i "movie={file},select=gt(scene\,0.05)" -show_entries packet=pts_time
```
Any gap > 3 s between scene changes → fail this gate.
