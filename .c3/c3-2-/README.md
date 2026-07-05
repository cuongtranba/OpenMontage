---
id: c3-2
c3-seal: c2d495e01b150e2290df337c83bec2a342c79d3ee5fa688911b26306f9f8ad00
title: Backlot Board
type: container
parent: c3-0
goal: 'The living storyboard: a local web server + browser UI that renders a production run''s stages, script, scene plan, decisions, and generated assets live from disk.'
---

## Goal

The living storyboard: a local web server + browser UI that renders a production run's stages, script, scene plan, decisions, and generated assets live from disk.

## Components

| ID | Name | Category | Status | Goal Contribution |
| --- | --- | --- | --- | --- |
| c3-210 | Backlot Server & Board UI |  | active | Render live production state from disk artifacts. |

## Responsibilities

Watches projects/<id>/ (project.json marker, checkpoints, artifacts, assets) and derives everything it shows — it is an observer, never a blocker: if the board fails, production continues. Started via `python -m backlot open <project-id>`. Owns no production state and writes nothing the engine reads.

## Complexity Assessment

Read-only by design, so risk is low; the main failure mode is a degraded board when a run skips canonical artifacts (e.g. hand-authored atelier runs that don't write checkpoints).
