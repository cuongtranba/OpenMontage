---
id: ref-instruction-layering
c3-seal: fe965ecfcad93f32898e0ba0b0c295b89418be0f47f989c549e133ee871aa5f6
title: Three-Layer Instruction Model
type: ref
goal: 'An AI agent orchestrating ~100 tools across 12 pipelines needs consistent knowledge routing: without a standard reading order, agents improvise prompts from memory, skip provider-specific guidance, and produce measurably worse output. This ref standardizes where each kind of knowledge lives and the order it is consumed.'
---

## Goal

An AI agent orchestrating ~100 tools across 12 pipelines needs consistent knowledge routing: without a standard reading order, agents improvise prompts from memory, skip provider-specific guidance, and produce measurably worse output. This ref standardizes where each kind of knowledge lives and the order it is consumed.

## Choice

Three explicit layers with a fixed reading order: (1) tools/ + registry — what exists, availability, cost, fallbacks; (2) skills/ — how OpenMontage wants tools used per pipeline/stage (director skills, meta skills); (3) .agents/skills/ — raw vendor/technology knowledge, mandatory before calling any generation tool (each tool names its Layer 3 skills in its agent_skills field). Skills are preferred over source code for tool usage; reading source is reserved for debugging and audits.

## Why

Putting orchestration knowledge in Python would fork the source of truth and make the agent's behavior untunable without code changes — the system's core premise is that the agent IS the intelligence and instructions are its program. Alternatives considered in the project's design: (a) hardcoding provider guidance in tool docstrings couples creative guidance to code releases and buries it away from the agent's reading path; (b) one flat skill layer mixes stable vendor knowledge with pipeline-specific policy, so a provider swap would force rewriting pipeline skills. The three-layer split lets vendor knowledge (Layer 3) ship independently of pipeline policy (Layer 2) and runtime facts (registry), which is exactly how the repo evolves in practice — provider tools and .agents/skills/ arrive together, pipelines change separately.

## How

The reading order, from AGENT_GUIDE.md (Layer Map):

```
1. registry / tool contract — discover what's available
2. relevant pipeline or creative skill (Layer 2) — know HOW to use it in this context
3. underlying vendor skill (Layer 3) — mandatory before calling any generation tool
```

REQUIRED: check the tool's `agent_skills` field (registry metadata) and read every listed skill before authoring prompts for that tool. OPTIONAL: reading tool source, only when a skill and the tool disagree (debugging/audit exception).

Control-flow decisions (stage advance, retry cap, gate enforcement) are NOT agent judgment — they are enforced mechanically by `lib/pipeline_executor.py` (c3-105), which reads only the pipeline manifest (Layer 1 registry facts) and never reads Layer 2 or Layer 3 skills.
