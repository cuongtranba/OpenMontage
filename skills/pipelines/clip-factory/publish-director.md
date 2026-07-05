# Publish Director - Clip Factory Pipeline

## When To Use

This stage packages the clip batch into a distribution plan. The goal is not just exported files. The goal is a usable content engine.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/publish_log.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["compose"]["render_report"]`, `state.artifacts["idea"]["brief"]`, `state.artifacts["script"]["script"]` | Outputs, rankings, and goals |
| Playbook | Active style playbook | Brand voice |

## Process

### 1. Lead With The Strongest Clip

Do not schedule by chronology. Schedule by ranking.

The first published clip should usually be:

- the strongest hook,
- the cleanest standalone clip,
- the clip most aligned with the batch goal.

### 2. Tailor Copy By Platform

Each platform needs its own tone and packaging:

- TikTok / Reels: direct, fast, hook-led
- Shorts: searchable, keyword-aware
- LinkedIn: insight-led and more professional
- X: short, punchy, opinion-friendly

### 3. Package The Batch Cleanly

Group by platform and include ready-to-paste text assets, not just video files.

### 4. Preserve Batch Truth

Store in `publish_log.metadata`:

- `clip_catalog`
- `posting_order`
- `platform_copy_map`
- `schedule_notes`

### 5. Quality Gate

- strongest clips lead the rollout,
- captions are platform-specific,
- export folders are usable without extra cleanup,
- the batch catalog clearly links ranking, file paths, and publishing intent.

## Common Pitfalls

- Publishing the whole batch on the same day.
- Using one caption everywhere.
- Losing the rank/order logic after rendering is complete.

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
