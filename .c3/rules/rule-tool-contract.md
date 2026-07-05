---
id: rule-tool-contract
c3-seal: b11e2b7a48353d8d78b34088ab0da650792065084f54b32b15e7e322c88a12ce
title: Tool Class Contract
type: rule
goal: Every production tool across all capability families must be discoverable by the registry and callable through one uniform surface, so pipelines, selectors, and cost tracking work without per-tool special cases.
---

## Goal

Every production tool across all capability families must be discoverable by the registry and callable through one uniform surface, so pipelines, selectors, and cost tracking work without per-tool special cases.

## Rule

All production tools subclass BaseTool, are named in PascalCase without a "Tool" suffix, and implement execute(inputs: dict) returning ToolResult.

## Golden Example

From tools/publishers/export_bundle.py:

```python
class ExportBundle(BaseTool):
    name = "export_bundle"
    version = "0.1.0"
    tier = ToolTier.PUBLISH
    capability = "publish"
    provider = "local"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL
```

REQUIRED: class name PascalCase, no "Tool" suffix (`ExportBundle`, not `ExportBundleTool`); `name`, `tier`, `capability`, `provider`, `runtime` metadata; `execute(inputs: dict) -> ToolResult` with `.success`/`.data`/`.error`. OPTIONAL: `agent_skills`, `best_for`, `not_good_for`, cost estimation overrides.

## Not This

| Anti-Pattern | Correct | Why Wrong Here |
| --- | --- | --- |
| class MusicGenTool | class MusicGen | "Tool" suffix breaks the project-wide naming convention and import expectations |
| tool.run(params) | tool.execute(params) returning ToolResult | run() is not the contract; callers depend on ToolResult fields |
| Raising exceptions for expected failures | ToolResult(success=False, error=...) | Pipelines branch on .success; uncaught raises break stage execution |
| Hardcoding provider lists in callers | registry.get_by_capability() | Silent staleness when providers are added or unavailable |

## Scope

All classes under tools/ intended for production use. Test helpers and lib/ utilities are exempt.
