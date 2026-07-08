"""Tests for lib/pipeline_executor.py — TDD-first.

Run:
    PYTHONPATH=. python -m pytest tests/test_pipeline_executor.py -x -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# Ensure project root is importable.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.checkpoint import (
    CheckpointValidationError,
    init_project,
    read_checkpoint,
)
from lib.pipeline_executor import PipelineExecutor, RunReport, StageResult

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

PIPELINE_TYPE = "framework-smoke"

# Minimal schema-valid artifacts for framework-smoke stages.
RESEARCH_BRIEF = {
    "version": "1.0",
    "topic": "Test Topic",
    "research_date": "2026-07-08",
    "landscape": {
        "existing_content": [
            {"title": "Vid 1", "source": "youtube", "angle": "tutorial", "what_it_covers": "basics"},
            {"title": "Vid 2", "source": "blog", "angle": "deep dive", "what_it_covers": "advanced"},
            {"title": "Vid 3", "source": "youtube", "angle": "comparison", "what_it_covers": "alternatives"},
        ],
        "saturated_angles": ["basic tutorial"],
        "underserved_gaps": ["misconceptions"],
    },
    "data_points": [
        {"claim": "73% prefer X", "source_url": "https://example.com/1", "credibility": "primary_source"},
        {"claim": "Market grew 40%", "source_url": "https://example.com/2", "credibility": "secondary_source"},
        {"claim": "Experts agree on Y", "source_url": "https://example.com/3", "credibility": "primary_source"},
    ],
    "audience_insights": {
        "common_questions": ["What is X?", "How does X work?", "Why X?"],
        "misconceptions": [{"myth": "X is slow", "reality": "X is fast"}],
        "knowledge_level": "Beginner",
    },
    "angles_discovered": [
        {"name": "Surprising Truth", "hook": "You think X is slow.", "type": "contrarian", "why_now": "New data"},
        {"name": "X From Scratch", "hook": "Build X in 5 minutes.", "type": "evergreen", "why_now": "Demand"},
        {"name": "Why X Matters", "hook": "X changed everything.", "type": "trending", "why_now": "Announcement"},
    ],
    "sources": [
        {"url": "https://example.com/1", "title": "Study", "used_for": "data_points"},
        {"url": "https://example.com/2", "title": "Report", "used_for": "data_points"},
        {"url": "https://example.com/3", "title": "Survey", "used_for": "data_points"},
        {"url": "https://example.com/4", "title": "Forum", "used_for": "audience_insights"},
        {"url": "https://example.com/5", "title": "Blog", "used_for": "landscape"},
    ],
}

SCRIPT = {
    "version": "1.0",
    "title": "Test Script",
    "total_duration_seconds": 60,
    "sections": [
        {"id": "s1", "text": "Hello world", "start_seconds": 0, "end_seconds": 10},
    ],
}


@pytest.fixture()
def tmp_pipeline_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def project_id() -> str:
    return "test-proj-001"


@pytest.fixture()
def executor(tmp_pipeline_dir: Path, project_id: str) -> PipelineExecutor:
    init_project(
        project_id,
        title="Test Project",
        pipeline_type=PIPELINE_TYPE,
        pipeline_dir=tmp_pipeline_dir,
    )
    return PipelineExecutor(
        project_id=project_id,
        pipeline_type=PIPELINE_TYPE,
        pipeline_dir=tmp_pipeline_dir,
    )


# ---------------------------------------------------------------------------
# Test 1: Happy path — both stages complete in manifest order
# ---------------------------------------------------------------------------

def test_happy_path_all_stages_complete(executor: PipelineExecutor, tmp_pipeline_dir: Path, project_id: str):
    """Both stages run, checkpoints written, report shows all_stages_complete."""
    call_log: list[str] = []

    def runner(stage: str, ctx: dict[str, Any]) -> StageResult:
        call_log.append(stage)
        artifacts = (
            {"research_brief": RESEARCH_BRIEF} if stage == "research"
            else {"script": SCRIPT}
        )
        return StageResult(
            artifacts=artifacts,
            status="completed",
            human_approved=True,
        )

    report = executor.run(runner)

    assert report.stopped_reason == "all_stages_complete"
    assert report.completed_stages == ["research", "script"]
    assert report.last_stage == "script"
    assert call_log == ["research", "script"]

    # Verify checkpoints on disk.
    cp_research = read_checkpoint(tmp_pipeline_dir, project_id, "research")
    assert cp_research is not None
    assert cp_research["status"] == "completed"
    cp_script = read_checkpoint(tmp_pipeline_dir, project_id, "script")
    assert cp_script is not None
    assert cp_script["status"] == "completed"


# ---------------------------------------------------------------------------
# Test 2: Gate stop — awaiting_human on first stage stops loop
# ---------------------------------------------------------------------------

def test_gate_stop_awaiting_human(executor: PipelineExecutor, tmp_pipeline_dir: Path, project_id: str):
    """Runner returns awaiting_human → loop stops, checkpoint status awaiting_human."""
    call_log: list[str] = []

    def runner(stage: str, ctx: dict[str, Any]) -> StageResult:
        call_log.append(stage)
        return StageResult(
            artifacts={"research_brief": RESEARCH_BRIEF},
            status="awaiting_human",
            human_approved=False,
        )

    report = executor.run(runner)

    assert report.stopped_reason == "awaiting_human"
    assert report.last_stage == "research"
    assert call_log == ["research"]

    cp = read_checkpoint(tmp_pipeline_dir, project_id, "research")
    assert cp is not None
    assert cp["status"] == "awaiting_human"

    # script stage not yet touched
    cp_script = read_checkpoint(tmp_pipeline_dir, project_id, "script")
    assert cp_script is None


# ---------------------------------------------------------------------------
# Test 3: Resume — after awaiting_human, second run() completes pipeline
# ---------------------------------------------------------------------------

def test_resume_after_awaiting_human(executor: PipelineExecutor, tmp_pipeline_dir: Path, project_id: str):
    """After gate stop, a second run() resumes at same stage and finishes."""
    resume_calls: list[tuple[str, dict]] = []

    # First run — research returns awaiting_human
    def runner_first(stage: str, ctx: dict[str, Any]) -> StageResult:
        return StageResult(
            artifacts={"research_brief": RESEARCH_BRIEF},
            status="awaiting_human",
            human_approved=False,
        )

    report1 = executor.run(runner_first)
    assert report1.stopped_reason == "awaiting_human"

    # Second run — research now approved, script completes
    def runner_resume(stage: str, ctx: dict[str, Any]) -> StageResult:
        resume_calls.append((stage, dict(ctx)))
        if stage == "research":
            return StageResult(
                artifacts={"research_brief": RESEARCH_BRIEF},
                status="completed",
                human_approved=True,
            )
        return StageResult(
            artifacts={"script": SCRIPT},
            status="completed",
            human_approved=True,
        )

    report2 = executor.run(runner_resume)
    assert report2.stopped_reason == "all_stages_complete"
    assert set(report2.completed_stages) >= {"research", "script"}

    # First call in second run should be research (same pending stage).
    assert resume_calls[0][0] == "research"
    first_ctx = resume_calls[0][1]
    # Context should include resuming_from_awaiting_human flag.
    assert first_ctx.get("resuming_from_awaiting_human") is True
    assert "pending_checkpoint" in first_ctx
    # Resume context keys are exactly base set + resume keys.
    assert set(first_ctx.keys()) == {
        "manifest_stage",
        "prior_artifacts",
        "attempt",
        "resuming_from_awaiting_human",
        "pending_checkpoint",
    }


# ---------------------------------------------------------------------------
# Test 4: Gate violation propagates — CheckpointValidationError raised
# ---------------------------------------------------------------------------

def test_gate_violation_propagates(executor: PipelineExecutor):
    """Runner returns completed with human_approved=False on gated stage → error."""

    def runner(stage: str, ctx: dict[str, Any]) -> StageResult:
        return StageResult(
            artifacts={"research_brief": RESEARCH_BRIEF},
            status="completed",
            human_approved=False,  # gate violation: research requires human_approved
        )

    with pytest.raises(CheckpointValidationError):
        executor.run(runner)


# ---------------------------------------------------------------------------
# Test 5a: Retry — runner returns retry twice then completed
# ---------------------------------------------------------------------------

def test_retry_eventually_succeeds(executor: PipelineExecutor, tmp_pipeline_dir: Path, project_id: str):
    """Runner returns retry twice then completed; attempt count increments in context."""
    attempt_log: list[int] = []

    def runner(stage: str, ctx: dict[str, Any]) -> StageResult:
        attempt = ctx["attempt"]
        attempt_log.append(attempt)
        if stage == "research" and attempt < 3:
            return StageResult(artifacts={}, status="retry")
        artifacts = (
            {"research_brief": RESEARCH_BRIEF} if stage == "research"
            else {"script": SCRIPT}
        )
        return StageResult(artifacts=artifacts, status="completed", human_approved=True)

    report = executor.run(runner)
    assert report.stopped_reason == "all_stages_complete"
    # Attempt 1, 2, then 3 for research; then attempt 1 for script.
    assert attempt_log[0] == 1
    assert attempt_log[1] == 2
    assert attempt_log[2] == 3  # succeeds on 3rd try


# ---------------------------------------------------------------------------
# Test 5b: Retry exhausted — retries_exhausted, failed checkpoint written
# ---------------------------------------------------------------------------

def test_retry_exhausted(executor: PipelineExecutor, tmp_pipeline_dir: Path, project_id: str):
    """Runner always returns retry → retries_exhausted + failed checkpoint."""

    def runner(stage: str, ctx: dict[str, Any]) -> StageResult:
        return StageResult(artifacts={}, status="retry")

    report = executor.run(runner)
    assert report.stopped_reason == "retries_exhausted"
    assert report.last_stage == "research"

    cp = read_checkpoint(tmp_pipeline_dir, project_id, "research")
    assert cp is not None
    assert cp["status"] == "failed"


# ---------------------------------------------------------------------------
# Test 6: Overhead metric — orchestration time is measured, runner time excluded
# ---------------------------------------------------------------------------

def test_overhead_metric(tmp_pipeline_dir: Path, project_id: str):
    """orchestration_overhead_seconds > 0, < 180; runner sleep NOT counted."""
    init_project(
        project_id,
        title="Timing Test",
        pipeline_type=PIPELINE_TYPE,
        pipeline_dir=tmp_pipeline_dir,
    )
    ex = PipelineExecutor(
        project_id=project_id,
        pipeline_type=PIPELINE_TYPE,
        pipeline_dir=tmp_pipeline_dir,
    )

    def runner(stage: str, ctx: dict[str, Any]) -> StageResult:
        time.sleep(0.2)  # should NOT be counted in overhead
        artifacts = (
            {"research_brief": RESEARCH_BRIEF} if stage == "research"
            else {"script": SCRIPT}
        )
        return StageResult(artifacts=artifacts, status="completed", human_approved=True)

    wall_start = time.perf_counter()
    report = ex.run(runner)
    wall = time.perf_counter() - wall_start

    assert report.orchestration_overhead_seconds > 0
    assert report.orchestration_overhead_seconds < 180  # anti-goal 2 budget
    # Runner slept 0.2s x 2 stages = 0.4s of wall time that must be excluded.
    assert report.orchestration_overhead_seconds <= wall - 0.35
    assert len(report.timings) > 0
    # All timing entries should have "op" and "seconds".
    for t in report.timings:
        assert "op" in t
        assert "seconds" in t


# ---------------------------------------------------------------------------
# Test 7: Context keys are exactly the documented set
# ---------------------------------------------------------------------------

def test_context_keys(executor: PipelineExecutor):
    """Context passed to runner has exactly the documented keys."""
    observed_keys: list[frozenset[str]] = []

    def runner(stage: str, ctx: dict[str, Any]) -> StageResult:
        observed_keys.append(frozenset(ctx.keys()))
        artifacts = (
            {"research_brief": RESEARCH_BRIEF} if stage == "research"
            else {"script": SCRIPT}
        )
        return StageResult(artifacts=artifacts, status="completed", human_approved=True)

    executor.run(runner)

    expected_base = frozenset({"manifest_stage", "prior_artifacts", "attempt"})
    for keys in observed_keys:
        assert expected_base == keys, f"Unexpected context keys: {keys}"


# ---------------------------------------------------------------------------
# Test 8: progress_sink receives events
# ---------------------------------------------------------------------------

def test_progress_sink_receives_events(tmp_pipeline_dir: Path, project_id: str):
    """progress_sink callable is called with orchestration_op events."""
    init_project(
        project_id,
        title="Sink Test",
        pipeline_type=PIPELINE_TYPE,
        pipeline_dir=tmp_pipeline_dir,
    )
    events: list[dict] = []
    ex = PipelineExecutor(
        project_id=project_id,
        pipeline_type=PIPELINE_TYPE,
        pipeline_dir=tmp_pipeline_dir,
        progress_sink=events.append,
    )

    def runner(stage: str, ctx: dict[str, Any]) -> StageResult:
        artifacts = (
            {"research_brief": RESEARCH_BRIEF} if stage == "research"
            else {"script": SCRIPT}
        )
        return StageResult(artifacts=artifacts, status="completed", human_approved=True)

    ex.run(runner)

    event_types = {e["event"] for e in events}
    assert "orchestration_op" in event_types
    assert "stage_enter" in event_types
    assert "stage_exit" in event_types


# ---------------------------------------------------------------------------
# Test 9: stage_failed stops loop
# ---------------------------------------------------------------------------

def test_stage_failed_stops_loop(executor: PipelineExecutor, tmp_pipeline_dir: Path, project_id: str):
    """Runner returns 'failed' → loop stops with stopped_reason='stage_failed'."""
    call_log: list[str] = []

    def runner(stage: str, ctx: dict[str, Any]) -> StageResult:
        call_log.append(stage)
        return StageResult(artifacts={}, status="failed", error="something broke")

    report = executor.run(runner)

    assert report.stopped_reason == "stage_failed"
    assert report.last_stage == "research"
    assert call_log == ["research"]

    cp = read_checkpoint(tmp_pipeline_dir, project_id, "research")
    assert cp is not None
    assert cp["status"] == "failed"
