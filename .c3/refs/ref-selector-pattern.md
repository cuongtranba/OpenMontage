---
id: ref-selector-pattern
c3-seal: 0cd4cbdaf44ca80eae715f5a1d9597cfac1595889dd2b69b77534782c71f170c
title: Capability Selector Pattern
type: ref
goal: Multi-provider capabilities (TTS, image generation, video generation) each have 3–13 interchangeable provider tools with different input schemas and availability. Pipeline stages need one stable way to request "a TTS render" without naming a provider, or every manifest and skill would need updating each time a provider is added or an API key changes.
---

## Goal

Multi-provider capabilities (TTS, image generation, video generation) each have 3–13 interchangeable provider tools with different input schemas and availability. Pipeline stages need one stable way to request "a TTS render" without naming a provider, or every manifest and skill would need updating each time a provider is added or an API key changes.

## Choice

One selector tool per multi-provider capability — tts_selector, image_selector, video_selector — that discovers providers at call time via registry.get_by_capability(), routes by user preference > availability > discovery order, and adapts input schemas between providers transparently. Adding a provider tool automatically extends the selector: no selector code changes.

## Why

The registry already knows every tool's capability and live availability, so routing on discovery beats maintaining routing tables. The alternative — pipeline manifests naming concrete provider tools — was rejected in the project's design because it breaks the setup-offer protocol (a machine with different API keys would need different manifests) and hides provider choice from the user, violating the decision-communication contract in AGENT_GUIDE.md. A second alternative, a single generic "generate" tool, would erase the per-provider contracts (cost, best_for, agent_skills) the proposal stage must surface to users.

## How

From AGENT_GUIDE.md (Selector Pattern):

```
| Selector | Routes to | How it discovers |
|----------|-----------|-----------------|
| tts_selector | All tools with capability="tts" | registry.get_by_capability("tts") |
| image_selector | All tools with capability="image_generation" | registry.get_by_capability("image_generation") |
| video_selector | All tools with capability="video_generation" | registry.get_by_capability("video_generation") |
```

REQUIRED: selectors discover through the registry, never a hardcoded provider list. REQUIRED: user provider preference wins when that provider is available.
