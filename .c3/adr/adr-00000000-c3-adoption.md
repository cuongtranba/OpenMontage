---
id: adr-00000000-c3-adoption
c3-seal: 76daea7c353b38724cc17da37fca8eae9d9f495349e22cd19d8b36b666fc2c61
title: C3 Architecture Documentation Adoption
type: adr
goal: 'Adopt C3 architecture documentation for OpenMontage: model the system top-down (system, containers, components, refs, rules), freeze the facts as shared truth, and route all future architecture changes through gated change-units.'
status: done
affects:
    - c3-0
---

## Goal

Adopt C3 architecture documentation for OpenMontage: model the system top-down (system, containers, components, refs, rules), freeze the facts as shared truth, and route all future architecture changes through gated change-units.

## Context

OpenMontage's architecture knowledge lived in prose (AGENT_GUIDE.md, PROJECT_CONTEXT.md) with no machine-checked model: no frozen facts, no citation graph, no gate between "someone edited a doc" and "the architecture changed". The system is an instruction-driven video production engine — a Python tool/pipeline engine (tools/, lib/, schemas/, pipeline_defs/, skills/), a read-only Backlot board (backlot/), and a Node Remotion render runtime (remotion-composer/) — coordinated by an AI agent. That agent needs a queryable, frozen topology to answer "where is X" and "what breaks if I change Y" without re-deriving the architecture from prose each session.

## Decision

Initialize C3 at rung-1 with the lean seed canvas: one system fact (c3-0), three containers matching the real runtime boundaries (c3-1 Production Engine, c3-2 Backlot Board, c3-3 Remotion Composer), eight components covering the foundation (registry, BaseTool contract, checkpoints, schemas) and feature surfaces (provider tools, pipeline instructions, board, scene stack), two refs capturing the load-bearing rationale (three-layer instruction model, selector pattern), and two rules capturing the enforceable standards (tool class contract, project workspace outputs). Every fact was authored as a create-patch in this genesis change-unit and materialized atomically; eval-specs bind each component/ref/rule to its code.

## Affected Topology

| Entity | Type | Why affected | Evidence | Governance review |
| --- | --- | --- | --- | --- |
| c3-0 | system | Created: system goal + abstract constraints authored | c3-0#n335@v2:sha256:1a9ec355218758de7c3b441cdb111d137eee071f768c08be29f0bd08cc231333 | Onboard audit (this unit) |
| c3-1 | container | Created with 6 components (c3-101..c3-111) | c3-1#n288@v2:sha256:8fbe90b52ed1b2a4f73e02537e49952626917ad99f216339de83a3552d332b5d | Onboard audit (this unit) |
| c3-2 | container | Created with component c3-210 | c3-2#n303@v2:sha256:e980d344798fe4b6aa1ff8ce929c1c76e4f2082a72856208ec33d422e624fe48 | Onboard audit (this unit) |
| c3-3 | container | Created with component c3-310 | c3-3#n313@v2:sha256:7f50fbe220ed1468efd733e9096c8d5690e022f6404fc9ee260fe44a27c22bf0 | Onboard audit (this unit) |

## Compliance Refs

| Ref | Why required | Evidence | Action |
| --- | --- | --- | --- |
| ref-instruction-layering | Created by this unit; governs c3-104, c3-110, c3-111 knowledge routing | ref-instruction-layering#n236@v1:sha256:849cce5d29aa1960d827449578f8d6e7e3a2e53fae1dd007a00c0d274da2c254 | create-ref |
| ref-selector-pattern | Created by this unit; governs c3-101 and c3-110 capability routing | ref-selector-pattern#n246@v1:sha256:448d702da8984850c316901b376b20da27beb349b1a3bfb54a3c81e479b9708a | create-ref |

## Compliance Rules

| Rule | Why required | Evidence | Action |
| --- | --- | --- | --- |
| rule-tool-contract | Created by this unit; binding on c3-101, c3-102, c3-110 tool shape | rule-tool-contract#n258@v1:sha256:1b6e7051987eb14aefe19cd5ad3b4d4aa56b76ff2085d168692fdbdf4f0f0fc8 | create-rule |
| rule-project-workspace | Created by this unit; binding on c3-103, c3-111, c3-210, c3-310 output paths | rule-project-workspace#n275@v1:sha256:0a8753bb9fc3b7d544f490c4894c946fb7e323e49761eee06b3a72e3bf3ee02a | create-rule |

## Verification

| Check | Result |
| --- | --- |
| c3 check | ok: true, 0 findings |
| c3 eval | 12/12 holds, 0 drift |
| c3 lookup tools/tool_registry.py | resolves to c3-101 with uses/rules edges |
| c3 list | 16 entities: 1 system, 3 containers, 8 components, 2 refs, 2 rules |
