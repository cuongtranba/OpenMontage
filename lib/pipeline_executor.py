"""Deterministic pipeline executor — pure state-machine driver.

The executor receives a caller-provided ``stage_runner`` callable and is
responsible ONLY for:

- Iterating stages via ``get_next_stage`` / ``get_stage_order``
- Writing ``in_progress``, terminal, and failure checkpoints
- Enforcing max-retry limits from the manifest's orchestration block
- Measuring orchestration overhead (time spent in infrastructure calls)
- Emitting structured events to an optional ``progress_sink``

Anti-goals (hard constraints — do NOT add these here):
- Reading skill files
- Making creative decisions
- Calling generation / AI tools
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from lib.checkpoint import (
    CheckpointValidationError,
    get_next_stage,
    init_project,
    read_checkpoint,
    write_checkpoint,
)
from lib.pipeline_loader import (
    get_stage_human_approval_default,
    get_stage_order,
    get_stage_review_focus,
    get_stage_skill,
    load_pipeline_readonly,
)
from lib.decision_log import upsert_decision
from lib.paths import PROJECTS_DIR

# Default max retries when the manifest does not declare an orchestration block.
_DEFAULT_MAX_REVISIONS = 3


@dataclass
class StageResult:
    """Value returned by the caller's ``stage_runner`` for one stage attempt."""

    artifacts: dict[str, Any]
    status: str  # "completed" | "awaiting_human" | "failed" | "retry"
    human_approved: bool = False
    review: Optional[dict[str, Any]] = None
    cost_snapshot: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


@dataclass
class RunReport:
    """Summary returned by :meth:`PipelineExecutor.run`."""

    completed_stages: list[str]
    stopped_reason: str  # "all_stages_complete" | "awaiting_human" | "stage_failed" | "retries_exhausted"
    last_stage: Optional[str]
    orchestration_overhead_seconds: float
    timings: list[dict[str, Any]]


class PipelineExecutor:
    """Drive a pipeline to completion via a caller-supplied ``stage_runner``.

    The executor is a pure state-machine driver.  All creative / AI work lives
    inside ``stage_runner`` — the executor never reads skill files, never makes
    creative decisions, and never calls generation tools.

    Parameters
    ----------
    project_id:
        Unique identifier for the project.
    pipeline_type:
        Name of the pipeline manifest (e.g. ``"framework-smoke"``).
    pipeline_dir:
        Root directory for project checkpoints.  Defaults to
        :data:`lib.paths.PROJECTS_DIR`.
    defs_dir:
        Override directory for pipeline manifests (``pipeline_defs/``).
        ``None`` uses the default.
    checkpoint_policy:
        Forwarded to every ``write_checkpoint`` call.
    style_playbook:
        Forwarded to ``write_checkpoint`` when set.
    progress_sink:
        Optional callable that receives structured event dicts for every
        orchestration operation.  Timing of the sink call itself is excluded
        from overhead measurement.
    """

    def __init__(
        self,
        project_id: str,
        pipeline_type: str,
        pipeline_dir: Optional[Path] = None,
        defs_dir: Optional[Path] = None,
        checkpoint_policy: str = "guided",
        style_playbook: Optional[str] = None,
        progress_sink: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        self._project_id = project_id
        self._pipeline_type = pipeline_type
        self._pipeline_dir = pipeline_dir or PROJECTS_DIR
        self._defs_dir = defs_dir
        self._checkpoint_policy = checkpoint_policy
        self._style_playbook = style_playbook
        self._progress_sink = progress_sink

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        stage_runner: Callable[[str, dict[str, Any]], StageResult],
    ) -> RunReport:
        """Drive the pipeline until it finishes, stalls, or fails.

        Parameters
        ----------
        stage_runner:
            ``(stage_name, context) -> StageResult``.  The executor provides
            context with these keys:

            - ``manifest_stage``: the raw stage dict from the manifest
            - ``prior_artifacts``: mapping of artifact name → artifact dict for
              every *completed* stage so far
            - ``attempt``: 1-based retry counter (1 on first call for a stage)

            When resuming from an ``awaiting_human`` checkpoint these extra keys
            are also present:

            - ``resuming_from_awaiting_human``: ``True``
            - ``pending_checkpoint``: the ``awaiting_human`` checkpoint dict

        Returns
        -------
        RunReport
        """
        overhead_seconds = 0.0
        timings: list[dict[str, Any]] = []
        completed_stages: list[str] = []
        last_stage: Optional[str] = None

        # Load manifest — timed as orchestration overhead.
        manifest = self._timed(
            "manifest_load",
            stage=None,
            timings=timings,
            fn=lambda: load_pipeline_readonly(self._pipeline_type, self._defs_dir),
        )
        overhead_seconds += timings[-1]["seconds"]

        max_revisions: int = (
            manifest.get("orchestration", {}).get("max_revisions_per_stage", _DEFAULT_MAX_REVISIONS)
        )

        while True:
            # Determine next stage.
            next_stage = self._timed(
                "get_next_stage",
                stage=None,
                timings=timings,
                fn=lambda: get_next_stage(
                    self._pipeline_dir, self._project_id, self._pipeline_type
                ),
            )
            overhead_seconds += timings[-1]["seconds"]

            if next_stage is None:
                return RunReport(
                    completed_stages=completed_stages,
                    stopped_reason="all_stages_complete",
                    last_stage=last_stage,
                    orchestration_overhead_seconds=overhead_seconds,
                    timings=timings,
                )

            stage = next_stage
            last_stage = stage

            # Find manifest stage dict for context.
            manifest_stage_dict: dict[str, Any] = {}
            for s in manifest.get("stages", []):
                if s["name"] == stage:
                    manifest_stage_dict = s
                    break

            # Build prior artifacts from completed checkpoints.
            prior_artifacts = self._timed(
                "collect_prior_artifacts",
                stage=stage,
                timings=timings,
                fn=lambda: self._collect_prior_artifacts(manifest),
            )
            overhead_seconds += timings[-1]["seconds"]

            # Emit stage_enter event.
            self._emit({"event": "stage_enter", "stage": stage})

            # Check for an existing awaiting_human checkpoint (resume path).
            pending_cp = self._timed(
                "read_checkpoint",
                stage=stage,
                timings=timings,
                fn=lambda: read_checkpoint(self._pipeline_dir, self._project_id, stage),
            )
            overhead_seconds += timings[-1]["seconds"]

            is_resuming = (
                pending_cp is not None
                and pending_cp.get("status") == "awaiting_human"
            )

            # Retry loop.
            attempt = 1
            while True:
                context: dict[str, Any] = {
                    "manifest_stage": manifest_stage_dict,
                    "prior_artifacts": prior_artifacts,
                    "attempt": attempt,
                }
                if is_resuming:
                    context["resuming_from_awaiting_human"] = True
                    context["pending_checkpoint"] = pending_cp

                # Write in_progress before calling runner.
                self._timed(
                    "write_checkpoint_in_progress",
                    stage=stage,
                    timings=timings,
                    fn=lambda: write_checkpoint(
                        self._pipeline_dir,
                        self._project_id,
                        stage,
                        "in_progress",
                        {},
                        pipeline_type=self._pipeline_type,
                        style_playbook=self._style_playbook,
                        checkpoint_policy=self._checkpoint_policy,
                    ),
                )
                overhead_seconds += timings[-1]["seconds"]

                # ---- Hand off to creative layer — NOT timed ----
                result: StageResult = stage_runner(stage, context)
                # ---- Back in orchestration layer ----------------

                if result.status == "retry":
                    if attempt >= max_revisions:
                        # Exhausted — write failed checkpoint.
                        self._timed(
                            "write_checkpoint_failed",
                            stage=stage,
                            timings=timings,
                            fn=lambda: write_checkpoint(
                                self._pipeline_dir,
                                self._project_id,
                                stage,
                                "failed",
                                result.artifacts,
                                pipeline_type=self._pipeline_type,
                                style_playbook=self._style_playbook,
                                checkpoint_policy=self._checkpoint_policy,
                                human_approval_required=bool(
                                    get_stage_human_approval_default(manifest, stage)
                                ),
                                error=f"Retries exhausted after {attempt} attempts",
                                metadata=result.metadata,
                            ),
                        )
                        overhead_seconds += timings[-1]["seconds"]
                        self._emit({"event": "stage_exit", "stage": stage, "status": "retries_exhausted"})
                        return RunReport(
                            completed_stages=completed_stages,
                            stopped_reason="retries_exhausted",
                            last_stage=stage,
                            orchestration_overhead_seconds=overhead_seconds,
                            timings=timings,
                        )
                    # Retry: increment attempt, loop again.
                    attempt += 1
                    is_resuming = False  # resuming flag only applies to first attempt
                    continue

                # Terminal result — write checkpoint.
                gate_required = bool(get_stage_human_approval_default(manifest, stage))

                # CheckpointValidationError propagates (gate violation loud).
                self._timed(
                    f"write_checkpoint_{result.status}",
                    stage=stage,
                    timings=timings,
                    fn=lambda: write_checkpoint(
                        self._pipeline_dir,
                        self._project_id,
                        stage,
                        result.status,
                        result.artifacts,
                        pipeline_type=self._pipeline_type,
                        style_playbook=self._style_playbook,
                        checkpoint_policy=self._checkpoint_policy,
                        human_approval_required=gate_required,
                        human_approved=result.human_approved,
                        review=result.review,
                        cost_snapshot=result.cost_snapshot,
                        error=result.error,
                        metadata=result.metadata,
                    ),
                )
                overhead_seconds += timings[-1]["seconds"]

                self._emit({"event": "stage_exit", "stage": stage, "status": result.status})

                if result.status == "completed":
                    completed_stages.append(stage)
                    break  # advance to next stage

                if result.status == "awaiting_human":
                    return RunReport(
                        completed_stages=completed_stages,
                        stopped_reason="awaiting_human",
                        last_stage=stage,
                        orchestration_overhead_seconds=overhead_seconds,
                        timings=timings,
                    )

                if result.status == "failed":
                    return RunReport(
                        completed_stages=completed_stages,
                        stopped_reason="stage_failed",
                        last_stage=stage,
                        orchestration_overhead_seconds=overhead_seconds,
                        timings=timings,
                    )

                # Unknown status — treat as failure.
                return RunReport(
                    completed_stages=completed_stages,
                    stopped_reason="stage_failed",
                    last_stage=stage,
                    orchestration_overhead_seconds=overhead_seconds,
                    timings=timings,
                )

    def next_contract(self) -> dict[str, Any]:
        """Resolve the next stage and return the agent-facing contract.

        Writes/refreshes the stage's in_progress checkpoint (carrying the
        persisted retry attempt). Returns {"done": True} when no stage
        remains. Surfaces control-flow facts only — never skill content.
        """
        stage = get_next_stage(self._pipeline_dir, self._project_id, self._pipeline_type)
        if stage is None:
            return {"done": True}

        manifest = self._manifest()
        sd = self._stage_dict(stage)
        attempt = self._read_attempt(stage)

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

        retry: bump persisted attempt; if exceeds max_revisions write failed
        checkpoint and stop. completed/awaiting_human/failed: route decisions
        through upsert_decision, write checkpoint (gate enforced in code).
        Returns next contract, {"done": True}, or {"stopped": ...}.
        """
        stage = get_next_stage(self._pipeline_dir, self._project_id, self._pipeline_type)
        if stage is None:
            return {"done": True}

        manifest = self._manifest()
        gate_required = bool(get_stage_human_approval_default(manifest, stage))

        if status == "retry":
            attempt = self._read_attempt(stage) + 1
            if attempt > self._max_revisions():
                write_checkpoint(
                    self._pipeline_dir, self._project_id, stage, "failed",
                    artifacts or {}, pipeline_type=self._pipeline_type,
                    checkpoint_policy=self._checkpoint_policy,
                    human_approval_required=gate_required,
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

        # Route decisions before the checkpoint.
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
            human_approval_required=gate_required,
            human_approved=human_approved, review=review,
            cost_snapshot=cost_snapshot, error=error,
        )

        if status == "awaiting_human":
            return {"stopped": "awaiting_human", "stage": stage}
        if status == "failed":
            return {"stopped": "stage_failed", "stage": stage}
        return self.next_contract()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_prior_artifacts(self, manifest: dict[str, Any]) -> dict[str, Any]:
        """Return canonical artifacts from all completed checkpoints."""
        from lib.checkpoint import CANONICAL_STAGE_ARTIFACTS

        prior: dict[str, Any] = {}
        for stage_name in get_stage_order(manifest):
            cp = read_checkpoint(self._pipeline_dir, self._project_id, stage_name)
            if cp and cp.get("status") == "completed":
                artifacts = cp.get("artifacts", {})
                canonical = CANONICAL_STAGE_ARTIFACTS.get(stage_name)
                if canonical and canonical in artifacts:
                    prior[canonical] = artifacts[canonical]
        return prior

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

    def _timed(
        self,
        op: str,
        stage: Optional[str],
        timings: list[dict[str, Any]],
        fn: Callable[[], Any],
    ) -> Any:
        """Execute ``fn``, record elapsed time, emit event, and return result."""
        t0 = time.perf_counter()
        result = fn()
        elapsed = time.perf_counter() - t0
        entry: dict[str, Any] = {"op": op, "stage": stage, "seconds": elapsed}
        timings.append(entry)
        self._emit({"event": "orchestration_op", **entry})
        return result

    def _emit(self, event: dict[str, Any]) -> None:
        """Send event to progress_sink if configured."""
        if self._progress_sink is not None:
            self._progress_sink(event)


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
    import sys

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
        print(str(exc), file=sys.stderr)
        return 1

    print(_json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
