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
