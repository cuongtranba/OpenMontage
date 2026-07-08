# Wire Pipeline Executor into Production Path — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the deterministic executor the mandated driver by adding an interactive `next`/`advance` CLI the LLM calls between creative turns, then amend the frozen C3 facts and `AGENT_GUIDE.md` to point at it.

**Architecture:** The LLM cannot be an in-process Python callback, so the executor exposes its state machine one step at a time over a CLI. `next` resolves the current stage and surfaces the manifest facts (which director skill to read, gate, retry attempt). The agent does creative work across its turns, then `advance` writes the checkpoint (code-enforced gate), tracks retries via persisted attempt count, and routes decisions through `upsert_decision()`. The in-process `run(stage_runner)` surface is unchanged for batch/CI.

**Tech Stack:** Python 3.14, argparse, pytest, jsonschema; existing `lib/checkpoint.py`, `lib/pipeline_loader.py`, `lib/decision_log.py`. C3 CLI (`c3x.sh`) for the architecture change-unit.

---

## File Structure

- **Modify `lib/pipeline_executor.py`** — add three methods to `PipelineExecutor` (`next_contract`, `advance`, private `_read_attempt`/`_stage_dict`/`_max_revisions`) and an argparse `__main__` block. The in-process `run()` and dataclasses stay as-is.
- **Create `tests/test_pipeline_executor_cli.py`** — interactive-driver tests (methods + `main()`).
- **Modify `AGENT_GUIDE.md`** — rewrite Orchestrator section, adjust Rule Zero and Re-log Changed Decisions.
- **Modify `PROJECT_CONTEXT.md`** — note the executor as control-flow driver (if the file references the orchestrator; verify at that task).
- **C3 change-unit** (`.c3/` via `c3 change` CLI only) — amend `ref-instruction-layering`, amend `c3-1`, add `c3-105`.

The interactive driver lives in the existing executor file (one cohesive responsibility: driving the pipeline). No new module — splitting `run()` from `next/advance` would fork the shared primitives.

---

## Preamble: environment

All work happens in the worktree `../OpenMontage-wire-executor` (branch `feat/wire-executor`), which already exists and already contains the merged executor + decision_log.

Python interpreter: `/Users/cuongtran/Desktop/repo/OpenMontage/.venv/bin/python`. Define once per shell:

```bash
cd /Users/cuongtran/Desktop/repo/OpenMontage-wire-executor
PY=/Users/cuongtran/Desktop/repo/OpenMontage/.venv/bin/python
```

Run ONLY the test files this plan touches — never the full suite (shared machine).

---

## Task 1: Persist retry attempt + stage-dict helper

**Files:**
- Modify: `lib/pipeline_executor.py` (add private helpers after `_collect_prior_artifacts`)
- Test: `tests/test_pipeline_executor_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_executor_cli.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.checkpoint import init_project, read_checkpoint, write_checkpoint
from lib.pipeline_executor import PipelineExecutor
from tests.test_pipeline_executor import RESEARCH_BRIEF, SCRIPT

PIPELINE = "framework-smoke"


@pytest.fixture
def proj(tmp_path: Path) -> tuple[str, Path]:
    pid = "cli-smoke"
    init_project(pid, title="CLI Smoke", pipeline_type=PIPELINE, pipeline_dir=tmp_path)
    return pid, tmp_path


def _ex(proj: tuple[str, Path]) -> PipelineExecutor:
    pid, pdir = proj
    return PipelineExecutor(pid, PIPELINE, pipeline_dir=pdir)


def test_read_attempt_defaults_to_one(proj: tuple[str, Path]):
    ex = _ex(proj)
    assert ex._read_attempt("research") == 1


def test_read_attempt_reads_in_progress_metadata(proj: tuple[str, Path]):
    pid, pdir = proj
    write_checkpoint(
        pdir, pid, "research", "in_progress",
        {}, pipeline_type=PIPELINE, metadata={"attempt": 2},
    )
    ex = _ex(proj)
    assert ex._read_attempt("research") == 2


def test_stage_dict_returns_manifest_stage(proj: tuple[str, Path]):
    ex = _ex(proj)
    sd = ex._stage_dict("research")
    assert sd["name"] == "research"
    assert sd["produces"] == "research_brief"


def test_max_revisions_from_manifest(proj: tuple[str, Path]):
    ex = _ex(proj)
    assert ex._max_revisions() == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$PY -m pytest tests/test_pipeline_executor_cli.py -q`
Expected: FAIL — `PipelineExecutor` has no `_read_attempt` / `_stage_dict` / `_max_revisions`.

- [ ] **Step 3: Write minimal implementation**

In `lib/pipeline_executor.py`, add imports at the top of the existing `lib.pipeline_loader` import group:

```python
from lib.pipeline_loader import (
    get_stage_human_approval_default,
    get_stage_order,
    get_stage_review_focus,
    get_stage_skill,
    load_pipeline_readonly,
)
```

Add these methods to `PipelineExecutor` (after `_collect_prior_artifacts`, before `_timed`):

```python
    def _manifest(self) -> dict[str, Any]:
        return load_pipeline_readonly(self._pipeline_type, self._defs_dir)

    def _stage_dict(self, stage: str) -> dict[str, Any]:
        for s in self._manifest()["stages"]:
            if s["name"] == stage:
                return s
        raise KeyError(f"stage {stage!r} not in manifest {self._pipeline_type!r}")

    def _max_revisions(self) -> int:
        orch = self._manifest().get("orchestration", {})
        return int(orch.get("max_revisions_per_stage", _DEFAULT_MAX_REVISIONS))

    def _read_attempt(self, stage: str) -> int:
        cp = read_checkpoint(self._pipeline_dir, self._project_id, stage)
        if cp and cp.get("status") == "in_progress":
            meta = cp.get("metadata") or {}
            return int(meta.get("attempt", 1))
        return 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `$PY -m pytest tests/test_pipeline_executor_cli.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add lib/pipeline_executor.py tests/test_pipeline_executor_cli.py
git commit -m "feat(executor): add retry-attempt persistence + manifest helpers"
```

---

## Task 2: `next_contract` — resolve stage and surface manifest facts

**Files:**
- Modify: `lib/pipeline_executor.py` (add `next_contract` public method)
- Test: `tests/test_pipeline_executor_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_executor_cli.py`:

```python
def test_next_contract_fresh_project(proj: tuple[str, Path]):
    ex = _ex(proj)
    c = ex.next_contract()
    assert c["done"] is False
    assert c["stage"] == "research"
    assert c["produces"] == "research_brief"
    assert c["human_approval_default"] is True
    assert c["attempt"] == 1
    assert c["max_revisions"] == 3
    assert c["prior_artifacts"] == []
    # director_skill is None for framework-smoke (no skill declared)
    assert "director_skill" in c
    assert "review_focus" in c
    assert "success_criteria" in c


def test_next_contract_writes_in_progress(proj: tuple[str, Path]):
    pid, pdir = proj
    ex = _ex(proj)
    ex.next_contract()
    cp = read_checkpoint(pdir, pid, "research")
    assert cp is not None
    assert cp["status"] == "in_progress"
    assert (cp.get("metadata") or {}).get("attempt") == 1


def test_next_contract_done_when_all_complete(proj: tuple[str, Path]):
    pid, pdir = proj
    for stage, art in (("research", {"research_brief": RESEARCH_BRIEF}),
                       ("script", {"script": SCRIPT})):
        write_checkpoint(pdir, pid, stage, "completed", art,
                         pipeline_type=PIPELINE, human_approved=True)
    ex = _ex(proj)
    assert ex.next_contract() == {"done": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$PY -m pytest tests/test_pipeline_executor_cli.py -k next_contract -q`
Expected: FAIL — no `next_contract`.

- [ ] **Step 3: Write minimal implementation**

Add to `PipelineExecutor` (public API region, after `run`):

```python
    def next_contract(self) -> dict[str, Any]:
        """Resolve the next stage and return the agent-facing contract.

        Writes/refreshes the stage's ``in_progress`` checkpoint (carrying the
        persisted retry ``attempt``). Returns ``{"done": True}`` when no stage
        remains. This surfaces control-flow facts only — never skill content.
        """
        stage = get_next_stage(self._pipeline_dir, self._project_id, self._pipeline_type)
        if stage is None:
            return {"done": True}

        manifest = self._manifest()
        sd = self._stage_dict(stage)
        attempt = self._read_attempt(stage)

        # Preserve any partial_progress already on the in_progress checkpoint.
        existing = read_checkpoint(self._pipeline_dir, self._project_id, stage)
        meta: dict[str, Any] = dict((existing or {}).get("metadata") or {})
        meta["attempt"] = attempt
        write_checkpoint(
            self._pipeline_dir, self._project_id, stage, "in_progress", {},
            pipeline_type=self._pipeline_type,
            checkpoint_policy=self._checkpoint_policy,
            style_playbook=self._style_playbook,
            metadata=meta,
        )

        completed = self._collect_prior_artifacts(manifest)
        return {
            "done": False,
            "stage": stage,
            "director_skill": get_stage_skill(manifest, stage),
            "produces": sd.get("produces"),
            "tools_available": sd.get("tools_available", []),
            "review_focus": get_stage_review_focus(manifest, stage),
            "success_criteria": sd.get("success_criteria", []),
            "human_approval_default": bool(get_stage_human_approval_default(manifest, stage)),
            "attempt": attempt,
            "max_revisions": self._max_revisions(),
            "prior_artifacts": sorted(completed.keys()),
        }
```

Note: `_collect_prior_artifacts(manifest)` returns a dict of artifact-name → artifact for completed stages (existing helper). We expose only its keys to stay lean.

- [ ] **Step 4: Run test to verify it passes**

Run: `$PY -m pytest tests/test_pipeline_executor_cli.py -k next_contract -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add lib/pipeline_executor.py tests/test_pipeline_executor_cli.py
git commit -m "feat(executor): add next_contract stage resolver"
```

---

## Task 3: `advance` — checkpoint, retry accounting, decision routing

**Files:**
- Modify: `lib/pipeline_executor.py` (add `advance` public method; import `upsert_decision`)
- Test: `tests/test_pipeline_executor_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_executor_cli.py`:

```python
from lib.checkpoint import CheckpointValidationError
from lib.decision_log import read_current_decisions


def _complete(ex, art):
    return ex.advance(status="completed", artifacts=art, human_approved=True)


def test_advance_completed_returns_next(proj: tuple[str, Path]):
    ex = _ex(proj)
    ex.next_contract()  # enter research
    nxt = _complete(ex, {"research_brief": RESEARCH_BRIEF})
    assert nxt["done"] is False
    assert nxt["stage"] == "script"


def test_full_walk_to_done(proj: tuple[str, Path]):
    ex = _ex(proj)
    ex.next_contract()
    _complete(ex, {"research_brief": RESEARCH_BRIEF})
    _complete(ex, {"script": SCRIPT})
    assert ex.next_contract() == {"done": True}


def test_advance_gate_violation_raises(proj: tuple[str, Path]):
    ex = _ex(proj)
    ex.next_contract()
    with pytest.raises(CheckpointValidationError):
        ex.advance(status="completed", artifacts={"research_brief": RESEARCH_BRIEF},
                   human_approved=False)


def test_advance_awaiting_human_stops(proj: tuple[str, Path]):
    pid, pdir = proj
    ex = _ex(proj)
    ex.next_contract()
    r = ex.advance(status="awaiting_human", artifacts={"research_brief": RESEARCH_BRIEF})
    assert r == {"stopped": "awaiting_human", "stage": "research"}
    assert read_checkpoint(pdir, pid, "research")["status"] == "awaiting_human"


def test_retry_increments_then_exhausts(proj: tuple[str, Path]):
    pid, pdir = proj
    ex = _ex(proj)
    ex.next_contract()                       # attempt 1
    r1 = ex.advance(status="retry")
    assert r1["stage"] == "research" and r1["attempt"] == 2
    r2 = ex.advance(status="retry")
    assert r2["attempt"] == 3
    r3 = ex.advance(status="retry")          # exceeds max_revisions=3
    assert r3 == {"stopped": "retries_exhausted", "stage": "research"}
    assert read_checkpoint(pdir, pid, "research")["status"] == "failed"


def test_advance_routes_decisions(proj: tuple[str, Path]):
    pid, pdir = proj
    ex = _ex(proj)
    ex.next_contract()
    decisions = [
        {"stage": "research", "category": "voice_selection",
         "subject": "Narration TTS provider", "selected": "openai_onyx",
         "options_considered": [{"option_id": "openai_onyx", "label": "OpenAI Onyx",
                                 "score": 0.8, "reason": "clear"}],
         "reason": "default"},
    ]
    ex.advance(status="completed", artifacts={"research_brief": RESEARCH_BRIEF},
               human_approved=True, decisions=decisions)
    cur = read_current_decisions(pid, pipeline_dir=pdir)
    assert cur[("voice_selection", "Narration TTS provider")]["selected"] == "openai_onyx"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$PY -m pytest tests/test_pipeline_executor_cli.py -k advance -q`
Expected: FAIL — no `advance`.

- [ ] **Step 3: Write minimal implementation**

Add the import (new import group near the others):

```python
from lib.decision_log import upsert_decision
```

Add to `PipelineExecutor` (after `next_contract`):

```python
    def advance(
        self,
        *,
        status: str,
        artifacts: Optional[dict[str, Any]] = None,
        human_approved: bool = False,
        review: Optional[dict[str, Any]] = None,
        cost_snapshot: Optional[dict[str, Any]] = None,
        decisions: Optional[list[dict[str, Any]]] = None,
        error: Optional[str] = None,
    ) -> dict[str, Any]:
        """Advance the current in_progress stage.

        - ``retry``: bump the persisted attempt; when it would exceed
          ``max_revisions`` write a ``failed`` checkpoint and stop.
        - ``completed`` / ``awaiting_human`` / ``failed``: route any decisions
          through ``upsert_decision`` (enforcing the (category, subject)
          invariant), then write the checkpoint (gate enforced in code).
        Returns the next contract, ``{"done": True}``, or a ``{"stopped": ...}``.
        """
        stage = get_next_stage(self._pipeline_dir, self._project_id, self._pipeline_type)
        if stage is None:
            return {"done": True}

        if status == "retry":
            attempt = self._read_attempt(stage) + 1
            if attempt > self._max_revisions():
                write_checkpoint(
                    self._pipeline_dir, self._project_id, stage, "failed",
                    artifacts or {}, pipeline_type=self._pipeline_type,
                    checkpoint_policy=self._checkpoint_policy,
                    error=f"Retries exhausted after {attempt - 1} attempts",
                )
                return {"stopped": "retries_exhausted", "stage": stage}
            existing = read_checkpoint(self._pipeline_dir, self._project_id, stage)
            meta = dict((existing or {}).get("metadata") or {})
            meta["attempt"] = attempt
            write_checkpoint(
                self._pipeline_dir, self._project_id, stage, "in_progress", {},
                pipeline_type=self._pipeline_type,
                checkpoint_policy=self._checkpoint_policy,
                style_playbook=self._style_playbook, metadata=meta,
            )
            sd = self._stage_dict(stage)
            manifest = self._manifest()
            return {
                "done": False, "stage": stage,
                "director_skill": get_stage_skill(manifest, stage),
                "produces": sd.get("produces"),
                "tools_available": sd.get("tools_available", []),
                "review_focus": get_stage_review_focus(manifest, stage),
                "success_criteria": sd.get("success_criteria", []),
                "human_approval_default": bool(get_stage_human_approval_default(manifest, stage)),
                "attempt": attempt, "max_revisions": self._max_revisions(),
                "prior_artifacts": sorted(self._collect_prior_artifacts(manifest).keys()),
            }

        # Route decisions before the checkpoint so the log is consistent even
        # if the gate rejects the write.
        for d in decisions or []:
            upsert_decision(
                self._project_id, stage=d["stage"], category=d["category"],
                subject=d["subject"], selected=d["selected"],
                options_considered=d["options_considered"], reason=d["reason"],
                pipeline_dir=self._pipeline_dir,
                user_visible=d.get("user_visible", True),
                user_approved=d.get("user_approved", False),
                confidence=d.get("confidence"),
            )

        write_checkpoint(
            self._pipeline_dir, self._project_id, stage, status, artifacts or {},
            pipeline_type=self._pipeline_type,
            checkpoint_policy=self._checkpoint_policy,
            style_playbook=self._style_playbook,
            human_approved=human_approved, review=review,
            cost_snapshot=cost_snapshot, error=error,
        )

        if status == "awaiting_human":
            return {"stopped": "awaiting_human", "stage": stage}
        if status == "failed":
            return {"stopped": "stage_failed", "stage": stage}
        return self.next_contract()
```

Note: decisions route before the gate check. A gate violation (`completed` without approval) raises after decisions are written — acceptable: the decision is a real choice the agent made; the log should reflect it. Tests assert the raise still happens.

- [ ] **Step 4: Run test to verify it passes**

Run: `$PY -m pytest tests/test_pipeline_executor_cli.py -k advance -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Run the whole CLI test file + the pre-existing executor/decision tests**

Run: `$PY -m pytest tests/test_pipeline_executor_cli.py tests/test_pipeline_executor.py tests/test_decision_log.py -q`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add lib/pipeline_executor.py tests/test_pipeline_executor_cli.py
git commit -m "feat(executor): add advance (checkpoint, retry cap, decision routing)"
```

---

## Task 4: argparse `__main__` CLI

**Files:**
- Modify: `lib/pipeline_executor.py` (add `main()` + `if __name__ == "__main__"`)
- Test: `tests/test_pipeline_executor_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_executor_cli.py`:

```python
import io
import contextlib

from lib.pipeline_executor import main


def _run_cli(argv: list[str]) -> dict:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(argv)
    assert code == 0, buf.getvalue()
    return json.loads(buf.getvalue())


def test_cli_next(proj: tuple[str, Path]):
    pid, pdir = proj
    out = _run_cli(["next", pid, PIPELINE, "--projects-dir", str(pdir)])
    assert out["stage"] == "research"


def test_cli_advance_walk(proj: tuple[str, Path], tmp_path: Path):
    pid, pdir = proj
    _run_cli(["next", pid, PIPELINE, "--projects-dir", str(pdir)])
    art = tmp_path / "rb.json"
    art.write_text(json.dumps({"research_brief": RESEARCH_BRIEF}))
    out = _run_cli(["advance", pid, PIPELINE, "--projects-dir", str(pdir),
                    "--status", "completed", "--artifact-file", str(art),
                    "--human-approved"])
    assert out["stage"] == "script"


def test_cli_gate_violation_exit_1(proj: tuple[str, Path], tmp_path: Path):
    pid, pdir = proj
    _run_cli(["next", pid, PIPELINE, "--projects-dir", str(pdir)])
    art = tmp_path / "rb.json"
    art.write_text(json.dumps({"research_brief": RESEARCH_BRIEF}))
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        code = main(["advance", pid, PIPELINE, "--projects-dir", str(pdir),
                     "--status", "completed", "--artifact-file", str(art)])
    assert code == 1
    assert "GATE VIOLATION" in buf.getvalue()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$PY -m pytest tests/test_pipeline_executor_cli.py -k cli -q`
Expected: FAIL — no `main`.

- [ ] **Step 3: Write minimal implementation**

Add at the end of `lib/pipeline_executor.py`:

```python
def _load_json(path: Optional[str]) -> Any:
    if not path:
        return None
    import json as _json
    with open(path, encoding="utf-8") as f:
        return _json.load(f)


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint: ``next`` and ``advance`` subcommands (JSON to stdout)."""
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="python -m lib.pipeline_executor")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def _common(p: "argparse.ArgumentParser") -> None:
        p.add_argument("project_id")
        p.add_argument("pipeline_type")
        p.add_argument("--projects-dir", default=None)
        p.add_argument("--defs-dir", default=None)

    p_next = sub.add_parser("next")
    _common(p_next)

    p_adv = sub.add_parser("advance")
    _common(p_adv)
    p_adv.add_argument("--status", required=True,
                       choices=["completed", "awaiting_human", "failed", "retry"])
    p_adv.add_argument("--artifact-file", default=None)
    p_adv.add_argument("--decisions-file", default=None)
    p_adv.add_argument("--review-file", default=None)
    p_adv.add_argument("--cost-file", default=None)
    p_adv.add_argument("--human-approved", action="store_true")
    p_adv.add_argument("--error", default=None)

    args = parser.parse_args(argv)

    ex = PipelineExecutor(
        args.project_id, args.pipeline_type,
        pipeline_dir=Path(args.projects_dir) if args.projects_dir else None,
        defs_dir=Path(args.defs_dir) if args.defs_dir else None,
    )

    try:
        if args.cmd == "next":
            result = ex.next_contract()
        else:
            result = ex.advance(
                status=args.status,
                artifacts=_load_json(args.artifact_file),
                human_approved=args.human_approved,
                review=_load_json(args.review_file),
                cost_snapshot=_load_json(args.cost_file),
                decisions=_load_json(args.decisions_file),
                error=args.error,
            )
    except CheckpointValidationError as exc:
        import sys
        print(str(exc), file=sys.stderr)
        return 1

    print(_json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `$PY -m pytest tests/test_pipeline_executor_cli.py -k cli -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Full file green**

Run: `$PY -m pytest tests/test_pipeline_executor_cli.py -q`
Expected: PASS (all CLI + method tests).

- [ ] **Step 6: Commit**

```bash
git add lib/pipeline_executor.py tests/test_pipeline_executor_cli.py
git commit -m "feat(executor): add next/advance argparse CLI entrypoint"
```

---

## Task 5: Fix the broken C3 seal (prerequisite for the change-unit)

**Files:** `.c3/` (CLI only — never hand-edit instance files)

- [ ] **Step 1: Inspect the drift**

```bash
c3() { C3X_MODE=agent bash /Users/cuongtran/.claude/skills/c3/bin/c3x.sh "$@"; }
c3 check 2>&1 | tail -30
```
Expected: reports a broken seal in `.c3/canvases/component.md` (a canvas definition — user-owned, so a hand-edit there is legal but must be resealed).

- [ ] **Step 2: Reseal canonical files**

```bash
c3 repair 2>&1 | tail -20
```
Expected: repair rebuilds the cache and reseals. Re-run `c3 check 2>&1 | tail -5` — expect a clean/validated report.

- [ ] **Step 3: If repair still fails — STOP and escalate**

If `c3 repair` cannot reseal (persistent "broken C3 seal"), do NOT hand-edit `.c3/`. Report to the user: the seal on `canvases/component.md` is broken and blocks the change-unit; ask whether to (a) restore that file from `git show HEAD:.c3/canvases/component.md`, or (b) proceed with the code + AGENT_GUIDE changes now and land the C3 amendment in a follow-up once the seal is fixed. This is a pre-existing issue — surface it, don't work around it.

- [ ] **Step 4: Commit only if repair changed sealed files**

```bash
git add .c3/
git commit -m "chore(c3): reseal canonical files (repair broken canvas seal)"
```
(Skip if `git status` shows no `.c3/` changes.)

---

## Task 6: C3 change-unit — amend frozen facts, add c3-105

**Files:** `.c3/` via `c3 change` CLI only. Do this only after Task 5 leaves `c3 check` clean.

- [ ] **Step 1: Open the change-unit**

```bash
c3 change new wire-executor 2>&1 | tail -20
```
Expected: creates an ADR + patch folder; prints the change-unit id and how to add patches. Follow the printed `help[]` hints — they are authoritative over this plan for exact patch syntax.

- [ ] **Step 2: Amend `ref-instruction-layering`**

Stage a patch that rewrites its "Why" and "How" to introduce the control-flow vs creative-content split. New "Why" must state: orchestration *control-flow* (stage transitions, gate enforcement, retry accounting, the decision-log (category, subject) invariant) lives in code — the pipeline executor — because it is deterministic and auditable; orchestration *creative content* (what each stage produces, prompt authoring, taste, review verdict) stays with the agent and the skill layers, where the tunability argument still holds. The three-layer reading order is unchanged but is now *invoked by* the executor's `next` contract rather than walked from prose. Use the `c3` change/patch command the `help[]` output names (do NOT `Edit` the `.c3/refs/*.md` file directly).

- [ ] **Step 3: Amend `c3-1` Production Engine responsibility**

Stage a patch changing the Responsibilities line from "Explicitly NOT responsible for orchestration decisions — the agent is the orchestrator." to: "Owns orchestration control-flow — the pipeline executor drives stage transitions, enforces human-approval gates and retry caps, and enforces the decision-log (category, subject) invariant. The agent owns creative content per stage, guided by the skill layers."

- [ ] **Step 4: Add component `c3-105`**

```bash
c3 add component c3-105 --container c3-1 --file - <<'EOF'
[body per the schema c3 prints; title: "Pipeline Executor & Decision Log";
 goal: "Deterministic driver: resolve/advance stages (next/advance CLI + in-process run(stage_runner)), enforce human-approval gates and per-stage retry caps, and enforce the decision-log (category, subject) invariant via upsert_decision. Never reads skills or makes creative choices."]
EOF
```
Fill the body to match the columns `c3 schema component` prints (check first: `c3 schema component`). Set `parent: c3-1`. Do NOT hand-write the c3-1 membership row — the tool synthesizes it.

- [ ] **Step 5: Review then apply the change-unit**

```bash
c3 change view <change-unit-id> 2>&1 | tail -40
c3 change apply <change-unit-id> 2>&1 | tail -20
c3 check 2>&1 | tail -5
```
Expected: `apply` flips all patches atomically; `check` stays clean.

- [ ] **Step 6: Commit**

```bash
git add .c3/
git commit -m "feat(c3): amend instruction-layering + c3-1, add c3-105 pipeline executor"
```

---

## Task 7: Rewrite AGENT_GUIDE.md Orchestrator section

**Files:**
- Modify: `AGENT_GUIDE.md` (Orchestrator section ~181-201; Rule Zero ~49-68; Re-log Changed Decisions ~117-121)

- [ ] **Step 1: Replace the Orchestrator section**

Replace the body of "## Orchestrator" (the numbered "The agent itself orchestrates..." list and Infrastructure files block) with:

```markdown
## Orchestrator

The pipeline executor drives the production state machine — the agent supplies
the creative work for each stage, the executor owns the control-flow.

`research -> proposal -> script -> scene_plan -> assets -> edit -> compose`

Interactive loop (one stage per pass):

1. Ask the executor for the current stage:
   `python -m lib.pipeline_executor next <project_id> <pipeline_type>`
   It returns JSON: the `stage`, the `director_skill` to read, what it
   `produces`, `tools_available`, `review_focus`, `success_criteria`, the
   `human_approval_default` gate, the retry `attempt`, and `prior_artifacts`.
   When it returns `{"done": true}` the pipeline is finished.
2. Read the `director_skill` it named (Layer 2), then the tool's Layer 3
   skills before calling any generation tool. Do the creative work; produce
   the canonical artifact.
3. Self-review (`skills/meta/reviewer.md`).
4. Advance:
   `python -m lib.pipeline_executor advance <project_id> <pipeline_type>
   --status completed --artifact-file <artifact.json>
   [--human-approved] [--decisions-file <decisions.json>]`
   The executor writes the checkpoint (gates enforced in code), records
   decisions via the (category, subject) invariant, and returns the next
   stage contract — or `{"stopped": "awaiting_human"}` at a gate.
5. At an `awaiting_human` gate: present the artifact summary, review findings,
   and cost snapshot, then END YOUR TURN. After the user approves, re-run
   `advance --status completed --human-approved`.

To retry a stage after a failed self-review, call
`advance --status retry`; the executor enforces the manifest's
`max_revisions_per_stage` cap. Batch / non-interactive callers use the
in-process `PipelineExecutor(...).run(stage_runner)` API instead.

Infrastructure files:

- `lib/pipeline_executor.py` — the executor (interactive `next`/`advance` CLI
  and in-process `run`); owns transitions, gates, and retry caps
- `lib/checkpoint.py` — checkpoint read/write, gate enforcement
- `lib/decision_log.py` — `upsert_decision` ((category, subject) invariant)
- `tools/cost_tracker.py` — budget governance
- `lib/pipeline_loader.py` — manifest loading and helpers
```

- [ ] **Step 2: Adjust "Re-log Changed Decisions (Binding)"**

At the end of that subsection (after the existing prose), add:

```markdown

**In practice:** pass changed decisions to `advance --decisions-file` (or call
`lib.decision_log.upsert_decision`). Reusing the same `(category, subject)`
pair is enforced in code — a revision appends a new entry and moves the prior
selection into `options_considered` automatically. Do not hand-edit
`decision_log.json`.
```

- [ ] **Step 3: Adjust Rule Zero**

In "## Rule Zero", after point 4 ("Execute stage by stage..."), add a sentence:

```markdown

Stage sequencing is resolved by `python -m lib.pipeline_executor next` — do not
choose the next stage yourself. Using the executor CLI is not "ad-hoc tool
calling"; the prohibition below is about bypassing the pipeline with direct
generation-API scripts.
```

- [ ] **Step 4: Verify PROJECT_CONTEXT.md**

Run: `grep -n "orchestrat\|get_next_stage\|state machine" PROJECT_CONTEXT.md`
If it describes the agent as the sole orchestrator, add one line noting the executor now owns control-flow (mirror the c3-1 wording). If no match, skip.

- [ ] **Step 5: Commit**

```bash
git add AGENT_GUIDE.md PROJECT_CONTEXT.md
git commit -m "docs(guide): drive pipeline via executor next/advance CLI"
```

---

## Task 8: Final verification + PR

- [ ] **Step 1: Scoped test run**

Run: `$PY -m pytest tests/test_pipeline_executor_cli.py tests/test_pipeline_executor.py tests/test_decision_log.py -q`
Expected: all pass.

- [ ] **Step 2: Smoke the CLI end-to-end by hand**

```bash
$PY -m pytest tests/test_pipeline_executor_cli.py -k full_walk -q
```
Expected: PASS (the `framework-smoke` walk to `{done:true}` via the executor).

- [ ] **Step 3: Anti-goal 1 guard — executor reads no skill content**

Run: `grep -nE "open\(.*skills|read_text\(.*skills|\.md" lib/pipeline_executor.py`
Expected: no matches (the CLI surfaces the skill *path* string only; it never opens skill files).

- [ ] **Step 4: C3 conformance**

```bash
c3 check 2>&1 | tail -5
c3 eval c3-105 2>&1 | tail -10   # if eval binding is set; otherwise skip
```
Expected: check clean.

- [ ] **Step 5: Push + PR**

```bash
git push -u origin feat/wire-executor
gh pr create --title "feat: drive pipeline via executor (interactive next/advance CLI)" \
  --body "See docs/superpowers/specs/2026-07-08-wire-executor-design.md. Wires the merged executor + decision_log into the production path; amends frozen C3 facts (ref-instruction-layering, c3-1, adds c3-105); rewrites the AGENT_GUIDE Orchestrator section. Interactive CLI: next resolves the stage + surfaces the director-skill path + gate; advance checkpoints (code gate), tracks retries, routes decisions through upsert_decision. run(stage_runner) unchanged for batch."
```

- [ ] **Step 6: Report the PR URL to the user.**

---

## Self-Review

**Spec coverage:**
- Interactive CLI `next`/`advance` → Tasks 2, 3, 4. ✓
- Persist `attempt` across calls → Task 1 + Tasks 2/3. ✓
- Decision routing through `upsert_decision` → Task 3 + Task 4 (`--decisions-file`). ✓
- Gate enforced in code → Task 3 (`test_advance_gate_violation_raises`), Task 4 (`test_cli_gate_violation_exit_1`). ✓
- `run(stage_runner)` unchanged → no task modifies it; Task 3 Step 5 re-runs its tests. ✓
- C3 change-unit (amend ref + c3-1, add c3-105) → Task 6; seal prereq → Task 5. ✓
- AGENT_GUIDE rewrite (Orchestrator, Rule Zero, Re-log Decisions) → Task 7. ✓
- Anti-goal 1 (no creative reads) → Task 8 Step 3. ✓
- Anti-goal 2 (overhead) → short-lived CLI calls; not separately tested (per-call startup is outside the in-run metric, as the spec states). ✓
- Testing plan (6 cases) → covered across Tasks 2–4 (method + CLI variants). ✓

**Placeholder scan:** C3 patch bodies in Task 6 are intentionally deferred to the `c3` CLI's own `help[]`/`schema` output (the exact patch syntax is tool-authoritative and must not be guessed); every code step has complete code. No TODO/TBD in code tasks.

**Type consistency:** `next_contract()` and the `retry` branch of `advance()` emit the identical contract dict shape (same keys). `advance()` is keyword-only, matching all call sites in tests and `main()`. `upsert_decision` kwargs match `lib/decision_log.py` (`stage`, `category`, `subject`, `selected`, `options_considered`, `reason`, `pipeline_dir`, `user_visible`, `user_approved`, `confidence`). `main()` returns `int`; tests assert `code == 0/1`.
