# Publish Director - Avatar Spokesperson Pipeline

## When To Use

Package the finished spokesperson outputs for delivery. This stage should make it obvious which file is the hero cut, which are derivatives, and what message or audience each version serves.

## Process

### 1. Label Deliverables Clearly

Distinguish:

- hero cut,
- vertical cutdown,
- square cutdown,
- language variants,
- watermark or review versions.

### 2. Keep Metadata Message-Led

Recommended metadata keys:

- `audience_segment`
- `cta_copy`
- `offer_name`
- `locale`
- `thumbnail_concept`

### 3. Package Review Notes

If the avatar path has limitations such as visible lip-sync risk, retain that note in the package instead of hiding it.

### 4. Quality Gate

- exports are clearly named,
- metadata matches the intended message,
- poster frame or thumbnail concept features the presenter cleanly,
- review notes stay attached to the package.

## Common Pitfalls

- Mixing hero and derivative exports without clear naming.
- Reusing generic metadata that ignores the spokesperson offer.
- Dropping risk notes that matter for downstream publishing teams.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.

## TikTok Direct Post (tiktok_publisher)

When the brief targets TikTok and `tiktok_publisher` is AVAILABLE in the registry:

1. Call `creator_info` first (the tool does this internally, but for the approval gate run it via the tool's client or a dry run) and present the REAL `privacy_level_options` to the user. Never assume `PUBLIC_TO_EVERYONE` — unaudited TikTok apps can only post `SELF_ONLY` / friends / followers.
2. At the publish checkpoint present: the final video path, the exact caption (`title`, hashtags inline, ≤2200 chars), and the privacy level choice. Wait for approval — this gate is `human_approval_default: true`.
3. Log the decision in `decision_log` (`category: "publish_target"`, subject: "TikTok direct post") with privacy level and caption.
4. After approval call `tiktok_publisher` with `video_path`, `title`, `privacy_level`. The tool always labels the post as AI-generated content (`is_aigc`).
5. Merge the returned `publish_log` entries with any `export_bundle` entries into the stage's canonical `publish_log` artifact.
6. Mind the platform caps: ~15 posts/day per creator, 6 API requests/min — relevant for clip-factory batch runs.

If the tool is UNAVAILABLE, offer the setup path from its `install_instructions` (env keys + `python3 scripts/tiktok_login.py`) instead of silently exporting only.
