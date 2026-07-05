---
target: c3-110
scope: whole
type: component
parent: c3-1
title: Provider Tools & Selectors
category: Feature
---
## Goal

Concrete generation and post-production capabilities behind one contract.

## Parent Fit

| Field | Value |
|---|---|
| Container | c3-1 Production Engine |
| Category | Feature |
| Code | tools/tts/, tools/video/, tools/audio/, tools/graphics/, tools/publishers/, tools/analysis/, tools/avatar/, tools/enhancement/, tools/capture/, tools/character/, tools/subtitle/ |
| Depended on by | every pipeline stage that generates or transforms media |

## Purpose

The full provider surface: TTS, image/video/music generation, composition (video_compose with FFmpeg/Remotion/HyperFrames engines), stitching, mixing, analysis, avatars, enhancement, and publishing. Three selector tools (tts_selector, image_selector, video_selector) route capability-level requests to whatever providers the registry reports available — adding a provider tool automatically extends the selector with no selector code change. Not responsible for creative decisions: prompt quality comes from Layer 3 skills the agent must read before calling any generation tool.

## Governance

| Reference | Type | Governs | Precedence | Notes |
|---|---|---|---|---|
| rule-tool-contract | rule | Every provider tool's class shape and result type | binding | Non-conforming tools are invisible to discovery |
| ref-selector-pattern | ref | Capability routing across providers | binding | Selectors adapt input schemas between providers |
| ref-instruction-layering | ref | Agents read the tool's agent_skills before use | binding | Layer 3 knowledge is not optional |

## Contract

| Surface | Direction | Contract | Boundary | Evidence |
|---|---|---|---|---|
| <tool>.execute(inputs) | IN/OUT | Provider-specific inputs per input_schema; media written to explicit output_path under projects/<id>/ | Python API + filesystem | tools/video/video_compose.py |
| tts_selector / image_selector / video_selector | IN | Capability-level request; routes by user preference > availability > discovery order | Python API | tools/tts/tts_selector.py |
| video_compose render_engines | OUT | Reports which of ffmpeg/remotion/hyperframes are available; routes on edit_decisions.render_runtime, never silently swaps | Python API | tools/video/video_compose.py |

## Derived Materials

| Material | Must derive from | Allowed variance | Evidence |
|---|---|---|---|
| Generated media in projects/<id>/assets/ | Contract — <tool>.execute(inputs) surface with explicit output_path | None — assets without manifest linkage are invisible to the board | schemas/artifacts/asset_manifest.schema.json |
