---
id: c3-0
c3-seal: 614ea39e4b2da4622f45f66df1e2e029b0c774c393fd3d2b9342fd76c5296b56
title: c3-init
goal: 'OpenMontage is an instruction-driven AI video production system: an AI agent reads declarative pipeline manifests and director skills, then drives Python tools to research, script, generate assets, edit, and compose finished videos with human approval gates at every consequential stage.'
---

## Goal

OpenMontage is an instruction-driven AI video production system: an AI agent reads declarative pipeline manifests and director skills, then drives Python tools to research, script, generate assets, edit, and compose finished videos with human approval gates at every consequential stage.

## Containers

| ID | Name | Boundary | Status | Responsibilities | Goal Contribution |
| --- | --- | --- | --- | --- | --- |
| c3-1 | Production Engine |  | active | The Python production engine: tool contract, registry discovery, pipeline state, artifact schemas, provider tools, and the declarative pipeline manifests + director skills the agent executes. | The Python production engine: tool contract, registry discovery, pipeline state, artifact schemas, provider tools, and the declarative pipeline manifests + director skills the agent executes. |
| c3-2 | Backlot Board |  | active | The living storyboard: a local web server + browser UI that renders a production run's stages, script, scene plan, decisions, and generated assets live from disk. | The living storyboard: a local web server + browser UI that renders a production run's stages, script, scene plan, decisions, and generated assets live from disk. |
| c3-3 | Remotion Composer |  | active | The Node.js/React render runtime: stock scene-type compositions (Explainer, CinematicRenderer) plus the atelier path for hand-authored bespoke compositions, invoked by video_compose via npx. | The Node.js/React render runtime: stock scene-type compositions (Explainer, CinematicRenderer) plus the atelier path for hand-authored bespoke compositions, invoked by video_compose via npx. |

## Abstract Constraints

| Constraint | Rationale | Affected Containers |
| --- | --- | --- |
| All production goes through a pipeline: manifest + stage director skills; no ad-hoc tool scripts | The intelligence lives in instructions, not improvised code; skipping skills produces measurably worse output | c3-1 |
| Python is tools + persistence only — no orchestration, creative, review, or checkpoint policy logic in code | The agent makes those decisions guided by instructions; encoding them in Python would fork the source of truth | c3-1, c3-2 |
| Human approval gates are binding: a gated stage cannot complete without human_approved=True | Users must control cost- and quality-consequential decisions (provider, spend, publish) | c3-1, c3-2 |
| Every run writes canonical JSON artifacts + checkpoints under projects/<id>/ | Artifacts are the inter-stage contract and the Backlot board's only data source | c3-1, c3-2 |
