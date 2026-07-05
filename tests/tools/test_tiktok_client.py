"""Tests for the TikTok client module (no live API calls)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.publishers.tiktok_client import (
    DEFAULT_CHUNK_SIZE,
    TikTokTokens,
    plan_chunks,
)


def test_tokens_roundtrip_and_permissions(tmp_path):
    path = tmp_path / "sub" / "tokens.json"
    tokens = TikTokTokens(
        access_token="at", refresh_token="rt", open_id="oid", expires_at=123.0
    )
    tokens.save(path)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    loaded = TikTokTokens.load(path)
    assert loaded == tokens


def test_tokens_load_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        TikTokTokens.load(tmp_path / "absent.json")


def test_plan_chunks_small_file_single_chunk():
    assert plan_chunks(4_000_000) == [(0, 3_999_999)]


def test_plan_chunks_exact_multiple():
    size = DEFAULT_CHUNK_SIZE * 3
    chunks = plan_chunks(size)
    assert len(chunks) == 3
    assert chunks[0] == (0, DEFAULT_CHUNK_SIZE - 1)
    assert chunks[-1] == (2 * DEFAULT_CHUNK_SIZE, size - 1)


def test_plan_chunks_remainder_folds_into_last():
    size = DEFAULT_CHUNK_SIZE * 2 + 1234
    chunks = plan_chunks(size)
    # TikTok rule: total_chunk_count = size // chunk_size; trailing bytes merge into the last chunk
    assert len(chunks) == 2
    assert chunks[0] == (0, DEFAULT_CHUNK_SIZE - 1)
    assert chunks[1] == (DEFAULT_CHUNK_SIZE, size - 1)


def test_plan_chunks_covers_every_byte_exactly_once():
    size = DEFAULT_CHUNK_SIZE * 4 + 987_654
    chunks = plan_chunks(size)
    pos = 0
    for start, end in chunks:
        assert start == pos
        pos = end + 1
    assert pos == size
