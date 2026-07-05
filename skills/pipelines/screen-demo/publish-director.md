# Publish Director - Screen Demo Pipeline

## When To Use

Package the finished demo so the user can publish it quickly and so the metadata reflects the actual task, result, and tools involved.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/publish_log.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["compose"]["render_report"]`, `state.artifacts["idea"]["brief"]`, `state.artifacts["script"]["script"]` | Video, brief, and sections |
| Playbook | Active style playbook | Thumbnail and copy tone |

## Process

### 1. Build Searchable Metadata

Screen-demo titles work best when they combine:

- task,
- tool,
- outcome.

Good patterns:

- `How to deploy on Vercel from Next.js`
- `Fix CORS in React + Express`
- `Set up GitHub Actions for Python tests`

Pull keywords from:

- software names,
- frameworks,
- commands,
- exact error text,
- outcome words such as `deploy`, `fix`, `connect`, `publish`, `ship`.

### 2. Use Chapter Markers As Navigation

Use script sections as the basis for chapter markers and packaging bullets. A good screen-demo package makes the workflow skimmable before the user even presses play.

### 3. Thumbnail Strategy

If a thumbnail concept is needed, it should show:

- the result state, not a generic setup screen,
- the recognizable tool surface,
- 2-4 words of value text.

Store the concept in `publish_log.metadata.thumbnail_concepts`.

### 4. Package By Platform

Prepare:

- video file,
- title and description/caption,
- chapter markers where relevant,
- keyword list,
- thumbnail concept notes.

For developer or product-demo content, also package:

- commands shown,
- software/version mentions,
- error terms if it is a troubleshooting demo.

### 5. Quality Gate

- metadata names the real tool and task,
- chapters match the actual rendered flow,
- export folders are clean and reusable,
- copy is tailored to the platform instead of duplicated.

## Common Pitfalls

- Publishing with generic titles that omit the actual software or task.
- Using the same caption for YouTube, LinkedIn, and short-form social.
- Building chapter markers from the script without checking the render.

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
