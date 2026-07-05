---
target: c3-101
scope: whole
type: component
parent: c3-1
title: Tool Registry
category: Foundation
---
## Goal

Discover every tool, report real availability and capability.

## Parent Fit

| Field | Value |
|---|---|
| Container | c3-1 Production Engine |
| Category | Foundation |
| Code | tools/tool_registry.py |
| Depended on by | every pipeline preflight, selectors, Backlot capability display |

## Purpose

Single source of truth for what tools exist and whether they can run right now. Walks the tools/ package, instantiates every BaseTool subclass, and exposes capability_catalog(), provider_catalog(), provider_menu_summary(), and support_envelope(). Preflight and the provider menu are built exclusively from this — agents must never hardcode provider names, API key names, or setup URLs. Not responsible for choosing among providers (selectors do that) or executing tools.

## Governance

| Reference | Type | Governs | Precedence | Notes |
|---|---|---|---|---|
| rule-tool-contract | rule | What a discoverable tool must look like | binding | Registry only discovers conforming BaseTool subclasses |
| ref-selector-pattern | ref | How capability routing consumes discovery | informs | Selectors call get_by_capability() |

## Contract

| Surface | Direction | Contract | Boundary | Evidence |
|---|---|---|---|---|
| registry.discover() | IN | Imports tools package, registers every BaseTool subclass, returns names | Python API | tools/tool_registry.py |
| provider_menu_summary() | OUT | Human-ready capability rollup: runtimes, configured/total counts, setup offers, runtime warnings | Python API | tools/tool_registry.py |
| support_envelope() | OUT | Full per-tool contract dump (slow, debugging only) | Python API | tools/tool_registry.py |
| get_by_capability(cap) | OUT | All tools declaring that capability, for selector routing | Python API | tools/tool_registry.py |

## Derived Materials

| Material | Must derive from | Allowed variance | Evidence |
|---|---|---|---|
| Preflight capability menu shown to users | Contract — provider_menu_summary() OUT surface | Presentation wording only | AGENT_GUIDE.md |
| Selector provider lists | Contract — get_by_capability(cap) OUT surface | None — no hardcoded provider lists | tools/tts/tts_selector.py |
