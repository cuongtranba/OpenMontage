# Publish Director - Hybrid Pipeline

## When To Use

Package the hybrid outputs so the hero cut and its derivatives stay organized and the source/support mix remains clear.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/publish_log.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["compose"]["render_report"]`, `state.artifacts["idea"]["brief"]`, `state.artifacts["script"]["script"]` | Final outputs and hybrid framing |
| Playbook | Active style playbook | Tone consistency |

## Process

### 1. Distinguish Master And Variants

Group outputs as:

- master cut,
- short-form derivatives,
- format variants,
- chaptered or contextual variants.

### 2. Preserve Source Truth In Packaging

If the project uses interview footage, screen recording, or product footage as its anchor, the metadata should reflect that instead of packaging it like a pure generated piece.

### 3. Store Cross-Output Notes

Recommended metadata keys:

- `master_output`
- `derivative_outputs`
- `source_mix_notes`
- `platform_copy_map`

### 4. Quality Gate

- master and variants are clearly labeled,
- metadata matches the true source mix,
- export folders are organized by purpose,
- the package is ready to use without manual cleanup.

## Common Pitfalls

- Hiding which output is the hero cut.
- Packaging a source-led project like a generic generated asset.
- Losing platform-specific copy and labeling across variants.

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
