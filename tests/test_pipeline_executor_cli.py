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
    assert sd["produces"] == ["research_brief"]


def test_max_revisions_from_manifest(proj: tuple[str, Path]):
    ex = _ex(proj)
    assert ex._max_revisions() == 3


def test_next_contract_fresh_project(proj: tuple[str, Path]):
    ex = _ex(proj)
    c = ex.next_contract()
    assert c["done"] is False
    assert c["stage"] == "research"
    assert c["produces"] == ["research_brief"]   # produces is a list in the manifest
    assert c["human_approval_default"] is True
    assert c["attempt"] == 1
    assert c["max_revisions"] == 3
    assert c["prior_artifacts"] == []
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
