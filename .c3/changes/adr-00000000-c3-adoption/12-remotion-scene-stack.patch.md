---
target: c3-310
scope: whole
type: component
parent: c3-3
title: Composition Scene Stack
category: Feature
---
## Goal

React scene types and renderers for composed video.

## Parent Fit

| Field | Value |
|---|---|
| Container | c3-3 Remotion Composer |
| Category | Feature |
| Code | remotion-composer/ |
| Depended on by | video_compose (_remotion_render path) in c3-110 |

## Purpose

The Remotion project video_compose invokes via npx: stock scene types (text_card, stat_card, callout, comparison, hero_title, terminal_scene, anime_scene, bar_chart, line_chart, pie_chart, kpi_grid, progress_bar) with spring-physics transitions, word-level caption burn, overlay types, and the atelier entry point (composition_mode: "atelier") for hand-authored bespoke compositions. Stock types are the templated path; atelier work treats them as a mechanics codex only. Not responsible for choosing the runtime — that decision is locked at proposal in edit_decisions.render_runtime.

## Governance

| Reference | Type | Governs | Precedence | Notes |
|---|---|---|---|---|
| rule-project-workspace | rule | Renders land in projects/<id>/renders/ | binding | video_compose passes explicit output paths |

## Contract

| Surface | Direction | Contract | Boundary | Evidence |
|---|---|---|---|---|
| cut schemas per scene type | IN | Each cut.type maps to a documented props schema | JSON handed over npx boundary | remotion-composer/SCENE_TYPES.md |
| Rendered MP4 | OUT | Deterministic render of edit_decisions at requested resolution/fps | Filesystem | remotion-composer/Root.tsx |

## Derived Materials

| Material | Must derive from | Allowed variance | Evidence |
|---|---|---|---|
| Templated compositions | Contract — cut schemas per scene type surface | Props/content only | remotion-composer/SCENE_TYPES.md |
| Atelier compositions | Contract — Rendered MP4 surface via bespoke code (engine mechanics reused, creative components never) | Full creative freedom; must not import stock scene looks | skills/meta/bespoke-composition.md |
