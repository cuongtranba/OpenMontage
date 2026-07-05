---
target: c3-2
scope: whole
type: container
parent: c3-0
title: Backlot Board
---
## Goal

The living storyboard: a local web server + browser UI that renders a production run's stages, script, scene plan, decisions, and generated assets live from disk.

## Components

| ID | Name | Category | Status | Goal Contribution |
|---|---|---|---|---|

## Responsibilities

Watches projects/<id>/ (project.json marker, checkpoints, artifacts, assets) and derives everything it shows — it is an observer, never a blocker: if the board fails, production continues. Started via `python -m backlot open <project-id>`. Owns no production state and writes nothing the engine reads.

## Complexity Assessment

Read-only by design, so risk is low; the main failure mode is a degraded board when a run skips canonical artifacts (e.g. hand-authored atelier runs that don't write checkpoints).
