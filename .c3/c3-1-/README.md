---
id: c3-1
c3-seal: 3b7e77c78bab5d6caf768d24cbf3080858f5749ee94ccbd6644045eca1272a6e
title: Production Engine
type: container
parent: c3-0
goal: 'The Python production engine: tool contract, registry discovery, pipeline state, artifact schemas, provider tools, and the declarative pipeline manifests + director skills the agent executes.'
---

## Goal

The Python production engine: tool contract, registry discovery, pipeline state, artifact schemas, provider tools, and the declarative pipeline manifests + director skills the agent executes.

## Components

| ID | Name | Category | Status | Goal Contribution |
| --- | --- | --- | --- | --- |
| c3-101 | Tool Registry |  | active | Discover every tool, report real availability and capability. |
| c3-102 | BaseTool Contract |  | active | One execution contract every production tool implements. |
| c3-103 | Pipeline State & Checkpoints |  | active | Persist run state; enforce human approval gates. |
| c3-104 | Artifact Schemas |  | active | Validate every canonical inter-stage artifact. |
| c3-110 | Provider Tools & Selectors |  | active | Concrete generation and post-production capabilities behind one contract. |
| c3-111 | Pipeline Manifests & Director Skills |  | active | The declarative instruction set the agent executes. |

## Responsibilities

Owns everything a production run needs on disk and in process: tool discovery and availability reporting (support envelope, provider menu), the BaseTool execution contract, checkpoint persistence with gate enforcement, canonical artifact validation, all provider tools (TTS, image/video generation, music, composition, publishing), and the pipeline_defs/ + skills/ instruction set the agent reads. Explicitly NOT responsible for orchestration decisions — the agent is the orchestrator.

## Complexity Assessment

Largest container by far (~100+ tools across 15 capability families). Key risks: silent tool-availability bugs (a tool reporting AVAILABLE that fails at run time breaks the governance contract) and instruction drift between skills and tool behavior.
