---
id: c3-105
c3-seal: a2f29e095917c9560012ac89b12bd35704f2db0a8959bf56c184691267d46ecb
title: Pipeline Executor & Decision Log
type: component
category: foundation
parent: c3-1
goal: Drive stage sequencing, retry cap, and gate enforcement; persist decision metadata.
uses:
    - rule-project-workspace
---

## Goal

Drive stage sequencing, retry cap, and gate enforcement; persist decision metadata.

## Parent Fit

| Field | Value |
| --- | --- |
| Container | c3-1 Production Engine |
| Category | Foundation |
| Code | lib/pipeline_executor.py, lib/decision_log.py |
| Depended on by | interactive CLI next/advance commands, API upsert_decision endpoint |

## Purpose

Interactive CLI driver for stage-by-stage pipeline execution. next_contract() resolves the next stage from on-disk checkpoints and writes an in_progress sentinel with the attempt counter; advance() writes the final checkpoint (completed/failed/awaiting_human), enforces max_revisions_per_stage from the manifest, raises CheckpointValidationError on gate violations before any write, and routes decisions to the decision log via upsert_decision(). Exposes batch path run(stage_runner) for automated test suites. Not responsible for creative decisions — tool choice, prompt quality, and artifact judgment remain entirely with the agent.

## Foundational Flow

| Aspect | Detail | Reference |
| --- | --- | --- |
| N.A - not applicable | N.A - not applicable | rule-project-workspace |
| N.A - not applicable | N.A - not applicable | rule-project-workspace |
| N.A - not applicable | N.A - not applicable | rule-project-workspace |
| N.A - not applicable | N.A - not applicable | rule-project-workspace |

## Business Flow

| Aspect | Detail | Reference |
| --- | --- | --- |
| N.A - not applicable | N.A - not applicable | rule-project-workspace |
| N.A - not applicable | N.A - not applicable | rule-project-workspace |
| N.A - not applicable | N.A - not applicable | rule-project-workspace |
| N.A - not applicable | N.A - not applicable | rule-project-workspace |

## Governance

| Reference | Type | Governs | Precedence | Notes |
| --- | --- | --- | --- | --- |
| rule-project-workspace | rule | Checkpoint and decision log writes land under projects/<id>/ | binding | next_contract and advance both validate the workspace path before writing |

## Contract

| Surface | Direction | Contract | Boundary | Evidence |
| --- | --- | --- | --- | --- |
| next_contract() -> dict | OUT | Resolves next stage, writes in_progress checkpoint with attempt counter, returns {stage, manifest_facts, attempt} | Python API | lib/pipeline_executor.py |
| advance(status, artifacts, human_approved, ...) -> dict | IN/OUT | Writes final checkpoint; raises CheckpointValidationError on gate violation before write; retries increment attempt in next next_contract() call | Python API | lib/pipeline_executor.py |
| upsert_decision(project_id, category, subject, ...) | IN | Inserts or updates decision log row keyed on (category, subject); enforces uniqueness invariant | Python API | lib/decision_log.py |

## Change Safety

| Risk | Trigger | Detection | Required Verification |
| --- | --- | --- | --- |
| N.A - not applicable | N.A - not applicable | N.A - not applicable | lib/pipeline_executor.py |
| N.A - not applicable | N.A - not applicable | N.A - not applicable | lib/pipeline_executor.py |

## Derived Materials

| Material | Must derive from | Allowed variance | Evidence |
| --- | --- | --- | --- |
| projects/<id>/checkpoint_<stage>.json | Contract — advance() IN/OUT surface | Status values and metadata schema only | schemas/checkpoints/checkpoint.schema.json |
| projects/<id>/decision_log.jsonl | Contract — upsert_decision() IN surface | Row schema only | lib/decision_log.py |
