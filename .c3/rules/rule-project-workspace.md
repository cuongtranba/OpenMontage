---
id: rule-project-workspace
c3-seal: fd2c6993c1537a37523ff69f8907f90ad9a055568542788e5e0ef1d4f3e20f0e
title: Project Workspace Outputs
type: rule
goal: Every run's outputs must be discoverable by the Backlot board and reproducible from one directory, across all pipelines, tools, and composition runtimes.
---

## Goal

Every run's outputs must be discoverable by the Backlot board and reproducible from one directory, across all pipelines, tools, and composition runtimes.

## Rule

All production outputs are written under projects/<project-id>/ via an explicit output_path — never to the repo root, cwd, or temp dirs.

## Golden Example

From lib/checkpoint.py — the canonical layout is created by init_project and all tools write inside it:

```python
def init_project(
    project_id: str,
    *,
    title: str,
    pipeline_type: str,
    pipeline_dir: Optional[Path] = None,
    style_playbook: Optional[str] = None,
) -> Path:
    """Initialize a project workspace with the canonical layout + marker file.

    Creates projects/<project_id>/ with the standard subdirectories and writes
    project.json — the marker the Backlot board uses to render a project's
    identity and stage rail before the first checkpoint exists.
```

REQUIRED: call init_project at pipeline initialization; pass explicit `output_path` under projects/<project-id>/ to every tool. REQUIRED: artifacts in artifacts/, media in assets/<kind>/, final renders in renders/.

## Not This

| Anti-Pattern | Correct | Why Wrong Here |
| --- | --- | --- |
| Tool writes to cwd or /tmp | Explicit output_path under projects/<id>/ | Assets outside the workspace are invisible to the board and violate the workspace contract |
| Atelier runs skipping artifacts/checkpoints | Write script/scene_plan equivalents + checkpoints like any run | The board is runtime-agnostic; runs that skip artifacts get a degraded board |

## Scope

Every pipeline run including atelier and HyperFrames-skill runs. The gitignored projects/ tree itself is regenerable and never committed.
