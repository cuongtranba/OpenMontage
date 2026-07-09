---
id: c3-1
c3-seal: c749466791f56c17e3ec96ad99025a9691f760f388be6c3e2b16683b647baa3a
title: Production Engine
type: container
parent: c3-0
goal: 'The Python production engine: tool contract, registry discovery, pipeline state, artifact schemas, provider tools, the declarative pipeline manifests + director skills the agent executes, and the interactive CLI executor that drives stage sequencing.'
---

## Goal

The Python production engine: tool contract, registry discovery, pipeline state, artifact schemas, provider tools, the declarative pipeline manifests + director skills the agent executes, and the interactive CLI executor that drives stage sequencing.

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

Owns everything a production run needs on disk and in process: tool discovery and availability reporting (support envelope, provider menu), the BaseTool execution contract, checkpoint persistence with gate enforcement, canonical artifact validation, all provider tools (TTS, image/video generation, music, composition, publishing), the pipeline_defs/ + skills/ instruction set the agent reads, and the interactive CLI executor that drives stage sequencing and retry accounting. Explicitly NOT responsible for creative decisions — the agent is the creative intelligence. Control-flow decisions (stage sequence, retry cap, gate enforcement) are owned by c3-105 Pipeline Executor & Decision Log, not the agent.

## Complexity Assessment

Largest container by far (~100+ tools across 15 capability families). Key risks: silent tool-availability bugs (a tool reporting AVAILABLE that fails at run time breaks the governance contract) and instruction drift between skills and tool behavior.
