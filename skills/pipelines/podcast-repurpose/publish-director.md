# Publish Director - Podcast Repurpose Pipeline

## When To Use

Package podcast-derived clips and companion assets so that every short-form piece points back to the episode instead of drifting as an isolated fragment.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/publish_log.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["compose"]["render_report"]`, `state.artifacts["idea"]["brief"]`, `state.artifacts["script"]["script"]` | Outputs, source truth, chapters |
| Playbook | Active style playbook | Brand voice |

## Process

### 1. Link Every Clip Back To The Episode

Each short-form asset should reference:

- show name,
- episode title or number,
- guest name where relevant,
- full episode destination.

### 2. Tailor The Copy

- Shorts / Reels / TikTok: hook-led and concise
- LinkedIn: insight-led and more contextual
- YouTube companion: chapter-rich and search-friendly

### 3. Sequence The Release

Recommended order:

1. strongest announcement clip
2. next-best insight clip
3. quote-led or guest-led follow-ups
4. remaining supporting clips

### 4. Store Cross-Linking Truth In Metadata

Recommended metadata keys:

- `episode_reference`
- `guest_tags`
- `posting_schedule`
- `clip_to_episode_map`

### 5. Quality Gate

- every clip points back to the episode,
- guest attribution is correct,
- copy matches the platform,
- the release order reflects actual clip strength.

## Common Pitfalls

- Publishing clips without clear episode references.
- Forgetting to tag or mention the guest when that audience matters.
- Reusing one caption style across every platform.

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
