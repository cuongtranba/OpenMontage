"""Tests for lib/decision_log.py — TDD: failing tests written first.

All tests use tmp_path as pipeline_dir so they never touch the real projects/.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_option(option_id: str) -> dict[str, Any]:
    return {
        "option_id": option_id,
        "label": option_id,
        "score": 0.8,
        "reason": f"test reason for {option_id}",
    }


def _upsert(tmp_path: Path, **kwargs: Any):
    """Call upsert_decision with sensible defaults."""
    from lib.decision_log import upsert_decision

    defaults: dict[str, Any] = {
        "project_id": "proj-test",
        "stage": "narration",
        "category": "voice_selection",
        "subject": "Narration TTS provider",
        "selected": "openai_onyx",
        "options_considered": [_minimal_option("openai_onyx")],
        "reason": "best quality",
        "pipeline_dir": tmp_path,
    }
    defaults.update(kwargs)
    return upsert_decision(**defaults)


def _log_path(tmp_path: Path, project_id: str = "proj-test") -> Path:
    return tmp_path / project_id / "decision_log.json"


def _load_log(tmp_path: Path, project_id: str = "proj-test") -> dict[str, Any]:
    return json.loads(_log_path(tmp_path, project_id).read_text())


# ---------------------------------------------------------------------------
# Test 1 — First upsert creates valid file with d-001
# ---------------------------------------------------------------------------

def test_first_upsert_creates_file(tmp_path: Path) -> None:
    result = _upsert(tmp_path)

    assert _log_path(tmp_path).exists(), "decision_log.json must be created"

    doc = _load_log(tmp_path)
    assert doc["version"] == "1.0"
    assert doc["project_id"] == "proj-test"
    assert len(doc["decisions"]) == 1

    entry = doc["decisions"][0]
    assert entry["decision_id"] == "d-001"
    assert entry["stage"] == "narration"
    assert entry["category"] == "voice_selection"
    assert entry["subject"] == "Narration TTS provider"
    assert entry["selected"] == "openai_onyx"
    assert entry["reason"] == "best quality"
    assert len(entry["options_considered"]) >= 1

    # Return value must be the new decision dict
    assert result["decision_id"] == "d-001"


# ---------------------------------------------------------------------------
# Test 2 — Golden round-trip: revise same (category, subject)
# ---------------------------------------------------------------------------

def test_golden_round_trip_revise_decision(tmp_path: Path) -> None:
    # First upsert: openai_onyx selected
    _upsert(
        tmp_path,
        selected="openai_onyx",
        options_considered=[_minimal_option("openai_onyx"), _minimal_option("chirp3")],
    )

    # Second upsert: same pair, now chirp3 selected
    _upsert(
        tmp_path,
        selected="chirp3",
        options_considered=[_minimal_option("chirp3")],
    )

    doc = _load_log(tmp_path)
    decisions = doc["decisions"]

    # Append-only: both entries must be present
    assert len(decisions) == 2, "File must have both entries (append-only)"

    first, second = decisions
    assert first["decision_id"] == "d-001"
    assert second["decision_id"] == "d-002"

    # Latest entry per read_current_decisions is chirp3
    from lib.decision_log import read_current_decisions
    current = read_current_decisions("proj-test", pipeline_dir=tmp_path)
    key = ("voice_selection", "Narration TTS provider")
    assert key in current
    assert current[key]["selected"] == "chirp3"
    assert current[key]["decision_id"] == "d-002"

    # chirp3 entry's options_considered must contain openai_onyx with rejected_because mentioning "superseded"
    chirp3_entry = second
    opt_ids = {o["option_id"] for o in chirp3_entry["options_considered"]}
    assert "openai_onyx" in opt_ids, "Prior selected option must appear in new options_considered"

    onyx_opt = next(o for o in chirp3_entry["options_considered"] if o["option_id"] == "openai_onyx")
    assert "rejected_because" in onyx_opt
    assert "superseded" in onyx_opt["rejected_because"].lower()


# ---------------------------------------------------------------------------
# Test 3 — Different subject same category → distinct current decisions
# ---------------------------------------------------------------------------

def test_different_subject_same_category(tmp_path: Path) -> None:
    _upsert(
        tmp_path,
        category="provider_selection",
        subject="TTS provider",
        selected="openai",
        options_considered=[_minimal_option("openai")],
    )
    _upsert(
        tmp_path,
        category="provider_selection",
        subject="Image provider",
        selected="replicate",
        options_considered=[_minimal_option("replicate")],
    )

    from lib.decision_log import read_current_decisions
    current = read_current_decisions("proj-test", pipeline_dir=tmp_path)

    assert ("provider_selection", "TTS provider") in current
    assert ("provider_selection", "Image provider") in current
    assert current[("provider_selection", "TTS provider")]["selected"] == "openai"
    assert current[("provider_selection", "Image provider")]["selected"] == "replicate"


# ---------------------------------------------------------------------------
# Test 4 — decision_id numbering continues from max existing
# ---------------------------------------------------------------------------

def test_decision_id_numbering_continues(tmp_path: Path) -> None:
    # Seed file with d-001 and d-007 (gap intentional)
    project_dir = tmp_path / "proj-test"
    project_dir.mkdir(parents=True, exist_ok=True)
    seed = {
        "version": "1.0",
        "project_id": "proj-test",
        "decisions": [
            {
                "decision_id": "d-001",
                "stage": "narration",
                "category": "voice_selection",
                "subject": "Some subject",
                "options_considered": [_minimal_option("opt_a")],
                "selected": "opt_a",
                "reason": "first",
            },
            {
                "decision_id": "d-007",
                "stage": "narration",
                "category": "music_source",
                "subject": "BG Music",
                "options_considered": [_minimal_option("opt_b")],
                "selected": "opt_b",
                "reason": "seventh",
            },
        ],
    }
    (project_dir / "decision_log.json").write_text(json.dumps(seed, indent=2))

    result = _upsert(tmp_path, category="composition_mode", subject="New thing", selected="opt_c",
                     options_considered=[_minimal_option("opt_c")])

    assert result["decision_id"] == "d-008", f"Expected d-008, got {result['decision_id']}"

    doc = _load_log(tmp_path)
    assert len(doc["decisions"]) == 3


# ---------------------------------------------------------------------------
# Test 5 — Invalid category → ValueError, file unchanged
# ---------------------------------------------------------------------------

def test_invalid_category_raises_value_error(tmp_path: Path) -> None:
    # Create a pre-existing file to verify it's untouched on failure
    project_dir = tmp_path / "proj-test"
    project_dir.mkdir(parents=True, exist_ok=True)
    initial_content = json.dumps({"version": "1.0", "project_id": "proj-test", "decisions": []}, indent=2)
    log_path = project_dir / "decision_log.json"
    log_path.write_text(initial_content)

    with pytest.raises(ValueError):
        _upsert(tmp_path, category="INVALID_CATEGORY_XYZ")

    # File must be untouched
    assert log_path.read_text() == initial_content


# ---------------------------------------------------------------------------
# Test 6 — Append-only: 3 upserts, order preserved, first entry not mutated
# ---------------------------------------------------------------------------

def test_append_only_three_upserts(tmp_path: Path) -> None:
    _upsert(tmp_path, selected="opt_a", options_considered=[_minimal_option("opt_a")])

    # Read first entry snapshot before further upserts
    doc_after_first = _load_log(tmp_path)
    first_entry_snapshot = copy.deepcopy(doc_after_first["decisions"][0])

    _upsert(tmp_path, selected="opt_b", options_considered=[_minimal_option("opt_b")])
    _upsert(tmp_path, selected="opt_c", options_considered=[_minimal_option("opt_c")])

    doc = _load_log(tmp_path)
    assert len(doc["decisions"]) == 3, "Must have 3 entries (append-only)"

    # Order preserved: d-001, d-002, d-003
    ids = [d["decision_id"] for d in doc["decisions"]]
    assert ids == ["d-001", "d-002", "d-003"]

    # First entry not mutated
    assert doc["decisions"][0] == first_entry_snapshot


# ---------------------------------------------------------------------------
# Test 7 — Interop with _merge_decision_log: no duplicate on re-merge
# ---------------------------------------------------------------------------

def test_no_duplicate_on_merge(tmp_path: Path) -> None:
    from lib.checkpoint import _merge_decision_log

    _upsert(tmp_path)

    doc = _load_log(tmp_path)
    assert len(doc["decisions"]) == 1

    # Merge the same document again (simulates checkpoint carrying same decision)
    _merge_decision_log(tmp_path, "proj-test", doc)

    doc_after = _load_log(tmp_path)
    assert len(doc_after["decisions"]) == 1, "Re-merging same decision_id must not duplicate"
