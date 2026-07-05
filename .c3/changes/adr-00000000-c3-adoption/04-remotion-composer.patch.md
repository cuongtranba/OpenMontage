---
target: c3-3
scope: whole
type: container
parent: c3-0
title: Remotion Composer
---
## Goal

The Node.js/React render runtime: stock scene-type compositions (Explainer, CinematicRenderer) plus the atelier path for hand-authored bespoke compositions, invoked by video_compose via npx.

## Components

| ID | Name | Category | Status | Goal Contribution |
|---|---|---|---|---|

## Responsibilities

Renders edit_decisions into final video when render_runtime="remotion": animates still images with spring physics, renders text/stat/chart/terminal scene types from cut schemas, burns word-level captions, and exposes the atelier entry point for one-off compositions. One of three peer runtimes inside video_compose (FFmpeg, Remotion, HyperFrames) — the runtime choice is locked at proposal and never silently swapped.

## Complexity Assessment

Node ≥ npx + node_modules must be present or the runtime reports unavailable; the stock scene-type catalog is the "templated" path and deliberately off-limits in atelier mode to avoid same-looking videos.
