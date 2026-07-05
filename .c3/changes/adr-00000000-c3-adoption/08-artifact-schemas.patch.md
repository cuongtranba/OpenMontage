---
target: c3-104
scope: whole
type: component
parent: c3-1
title: Artifact Schemas
category: Foundation
---
## Goal

Validate every canonical inter-stage artifact.

## Parent Fit

| Field | Value |
|---|---|
| Container | c3-1 Production Engine |
| Category | Foundation |
| Code | schemas/artifacts/, schemas/checkpoints/, schemas/pipelines/, schemas/styles/ |
| Depended on by | checkpoint writer, tools emitting artifacts, stage handoffs |

## Purpose

JSON Schema definitions for every canonical artifact a stage produces (brief, script, scene_plan, asset_manifest, edit_decisions, render_report, publish_log, decision_log, ...) plus checkpoint, pipeline manifest, and style playbook schemas. validate_artifact() is the single validation entry point; an invalid canonical artifact is a contract violation that must fail fast, not degrade. Not responsible for producing artifacts — stage director skills define content, tools emit it.

## Governance

| Reference | Type | Governs | Precedence | Notes |
|---|---|---|---|---|
| ref-instruction-layering | ref | Schemas are the machine layer of the stage contract; skills define meaning | informs | Layer 2 skills reference artifact fields |

## Contract

| Surface | Direction | Contract | Boundary | Evidence |
|---|---|---|---|---|
| validate_artifact(name, payload) | IN | Raises on schema violation; callers fail fast | Python API | schemas/artifacts/__init__.py |
| schemas/artifacts/*.schema.json | OUT | Draft 2020-12 JSON Schemas, one per canonical artifact | JSON Schema files | schemas/artifacts/publish_log.schema.json |

## Derived Materials

| Material | Must derive from | Allowed variance | Evidence |
|---|---|---|---|
| Stage canonical artifacts in projects/<id>/artifacts/ | Contract — validate_artifact(name, payload) surface | None — invalid artifacts fail fast | schemas/artifacts/__init__.py |
