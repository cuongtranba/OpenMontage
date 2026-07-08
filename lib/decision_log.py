"""Decision log API for OpenMontage.

Codifies the invariant: a decision is identified by its (category, subject) pair.
Changing a logged choice must APPEND a new entry (append-only; never mutate or
reorder existing entries) while carrying the prior selected option into the new
entry's options_considered with rejected_because="superseded by revised decision".

The file format follows schemas/artifacts/decision_log.schema.json exactly.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from schemas.artifacts import validate_artifact


def _log_path(pipeline_dir: Path, project_id: str) -> Path:
    return pipeline_dir / project_id / "decision_log.json"


def _load_or_create(path: Path, project_id: str) -> dict[str, Any]:
    """Load the decision log JSON, or return the empty skeleton if missing."""
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"version": "1.0", "project_id": project_id, "decisions": []}


def _next_decision_id(decisions: list[dict[str, Any]]) -> str:
    """Return next d-NNN id based on the max NNN found in existing decisions."""
    max_n = 0
    pattern = re.compile(r"^d-(\d+)$")
    for d in decisions:
        m = pattern.match(d.get("decision_id", ""))
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"d-{max_n + 1:03d}"


def _find_prior(
    decisions: list[dict[str, Any]], category: str, subject: str
) -> Optional[dict[str, Any]]:
    """Return the latest entry (scan from end) matching (category, subject)."""
    for entry in reversed(decisions):
        if entry.get("category") == category and entry.get("subject") == subject:
            return entry
    return None


def _find_option(options: list[dict[str, Any]], option_id: str) -> Optional[dict[str, Any]]:
    """Find an option by option_id."""
    for opt in options:
        if opt.get("option_id") == option_id:
            return opt
    return None


def upsert_decision(
    project_id: str,
    *,
    stage: str,
    category: str,
    subject: str,
    selected: str,
    options_considered: list[dict[str, Any]],
    reason: str,
    pipeline_dir: Optional[Path] = None,
    user_visible: bool = True,
    user_approved: bool = False,
    confidence: Optional[float] = None,
) -> dict[str, Any]:
    """Append a new decision entry to the project's decision_log.json.

    If a prior entry with the same (category, subject) exists and its selected
    option is not already in options_considered, that option is appended with
    rejected_because="superseded by revised decision".

    The file is never mutated in-place: new entries are always appended. An
    atomic write (temp + os.replace) prevents partial writes.

    Validation against the schema runs *before* the file is touched; an invalid
    entry raises ValueError and leaves the file unchanged.

    Not safe for concurrent writers: read-modify-write with no lock. Fine for
    the single-agent local runs OpenMontage does today.

    Returns the new decision dict.
    """
    from lib.paths import PROJECTS_DIR  # local import to allow pipeline_dir override

    base_dir = pipeline_dir if pipeline_dir is not None else PROJECTS_DIR
    path = _log_path(base_dir, project_id)

    doc = _load_or_create(path, project_id)
    decisions: list[dict[str, Any]] = doc["decisions"]

    # --- Build the new options_considered list (copy so caller's list is safe)
    new_options: list[dict[str, Any]] = [dict(o) for o in options_considered]

    # --- Carry forward prior selected option if this is a revision
    prior = _find_prior(decisions, category, subject)
    if prior is not None:
        prior_selected_id: str = prior["selected"]
        already_present = any(o.get("option_id") == prior_selected_id for o in new_options)
        if not already_present:
            # Try to copy the option object from the prior entry's options_considered
            prior_opt = _find_option(prior.get("options_considered", []), prior_selected_id)
            if prior_opt is not None:
                carried: dict[str, Any] = {
                    "option_id": prior_opt["option_id"],
                    "label": prior_opt["label"],
                    "score": prior_opt["score"],
                    "reason": prior_opt["reason"],
                    "rejected_because": "superseded by revised decision",
                }
            else:
                # Synthesize minimal option if not found
                carried = {
                    "option_id": prior_selected_id,
                    "label": prior_selected_id,
                    "score": 0.0,
                    "reason": "previous selection",
                    "rejected_because": "superseded by revised decision",
                }
            new_options.append(carried)

    # --- Assemble the new entry
    decision_id = _next_decision_id(decisions)
    new_entry: dict[str, Any] = {
        "decision_id": decision_id,
        "stage": stage,
        "category": category,
        "subject": subject,
        "options_considered": new_options,
        "selected": selected,
        "reason": reason,
        "user_visible": user_visible,
        "user_approved": user_approved,
    }
    if confidence is not None:
        new_entry["confidence"] = confidence

    # --- Validate full document before touching the file
    candidate_decisions = decisions + [new_entry]
    candidate_doc: dict[str, Any] = {
        "version": doc["version"],
        "project_id": doc["project_id"],
        "decisions": candidate_decisions,
    }
    try:
        validate_artifact("decision_log", candidate_doc)
    except Exception as exc:
        raise ValueError(
            f"New decision entry failed schema validation: {exc}"
        ) from exc

    # --- Atomic write: temp file + os.replace (same pattern as lib/checkpoint.py)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(candidate_doc, f, indent=2)
    os.replace(tmp_path, path)

    return new_entry


def read_current_decisions(
    project_id: str,
    pipeline_dir: Optional[Path] = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Return the latest decision entry per (category, subject) pair.

    Mirrors the Backlot board's logic: array position = recency.
    Later entries in the array override earlier ones for the same pair.
    """
    from lib.paths import PROJECTS_DIR

    base_dir = pipeline_dir if pipeline_dir is not None else PROJECTS_DIR
    path = _log_path(base_dir, project_id)

    if not path.exists():
        return {}

    with open(path, encoding="utf-8") as f:
        doc = json.load(f)

    current: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in doc.get("decisions", []):
        key = (entry.get("category", ""), entry.get("subject", ""))
        current[key] = entry  # later entries overwrite earlier ones

    return current
