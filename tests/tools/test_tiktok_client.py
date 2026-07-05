"""Tests for the TikTok client module (no live API calls)."""

import sys
import time as _time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.publishers.tiktok_client import (
    DEFAULT_CHUNK_SIZE,
    CreatorInfo,
    TikTokAPIError,
    TikTokAuthError,
    TikTokClient,
    TikTokTokens,
    TokenStore,
    exchange_code,
    plan_chunks,
    refresh_tokens,
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


def _json_response(payload, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def test_refresh_tokens_persists_rotation():
    payload = {
        "access_token": "new_at",
        "refresh_token": "rotated_rt",
        "open_id": "oid",
        "expires_in": 86400,
    }
    with patch("tools.publishers.tiktok_client.requests.post", return_value=_json_response(payload)) as post:
        tokens = refresh_tokens("key", "secret", "old_rt")
    assert tokens.access_token == "new_at"
    assert tokens.refresh_token == "rotated_rt"  # rotated value kept
    assert tokens.expires_at > _time.time()
    sent = post.call_args.kwargs["data"]
    assert sent["grant_type"] == "refresh_token"
    assert sent["refresh_token"] == "old_rt"


def test_refresh_tokens_failure_raises_auth_error():
    payload = {"error": "invalid_grant", "error_description": "expired"}
    with patch("tools.publishers.tiktok_client.requests.post", return_value=_json_response(payload, 400)):
        with pytest.raises(TikTokAuthError):
            refresh_tokens("key", "secret", "dead_rt")


def test_token_store_returns_unexpired_without_refresh(tmp_path):
    path = tmp_path / "tokens.json"
    TikTokTokens("at", "rt", "oid", _time.time() + 3600).save(path)
    store = TokenStore(path)
    with patch("tools.publishers.tiktok_client.requests.post") as post:
        tokens = store.fresh("key", "secret")
    post.assert_not_called()
    assert tokens.access_token == "at"


def test_token_store_refreshes_expired_and_saves(tmp_path):
    path = tmp_path / "tokens.json"
    TikTokTokens("old_at", "rt", "oid", _time.time() - 10).save(path)
    payload = {"access_token": "new_at", "refresh_token": "rt2", "open_id": "oid", "expires_in": 86400}
    with patch("tools.publishers.tiktok_client.requests.post", return_value=_json_response(payload)):
        tokens = TokenStore(path).fresh("key", "secret")
    assert tokens.access_token == "new_at"
    assert TikTokTokens.load(path).refresh_token == "rt2"  # rotation persisted


def test_token_store_missing_file_raises_auth_error(tmp_path):
    with pytest.raises(TikTokAuthError):
        TokenStore(tmp_path / "none.json").fresh("key", "secret")


def _client() -> TikTokClient:
    return TikTokClient(TikTokTokens("at", "rt", "oid", _time.time() + 3600))


def test_creator_info_parses_fields():
    payload = {
        "data": {
            "creator_username": "nevermind780",
            "creator_nickname": "Never mind",
            "privacy_level_options": ["FOLLOWER_OF_CREATOR", "SELF_ONLY"],
            "max_video_post_duration_sec": 3600,
        },
        "error": {"code": "ok", "message": "", "log_id": "x"},
    }
    with patch("tools.publishers.tiktok_client.requests.post", return_value=_json_response(payload)):
        info = _client().creator_info()
    assert info == CreatorInfo(
        username="nevermind780",
        nickname="Never mind",
        privacy_level_options=["FOLLOWER_OF_CREATOR", "SELF_ONLY"],
        max_video_post_duration_sec=3600,
    )


def test_api_error_envelope_raises():
    payload = {"data": {}, "error": {"code": "spam_risk_too_many_posts", "message": "cap", "log_id": "L"}}
    with patch("tools.publishers.tiktok_client.requests.post", return_value=_json_response(payload)):
        with pytest.raises(TikTokAPIError) as exc:
            _client().creator_info()
    assert exc.value.code == "spam_risk_too_many_posts"


def test_init_video_post_returns_ids_and_sends_is_fields():
    payload = {
        "data": {"publish_id": "v_pub~1", "upload_url": "https://open-upload.tiktokapis.com/u"},
        "error": {"code": "ok", "message": "", "log_id": "x"},
    }
    with patch("tools.publishers.tiktok_client.requests.post", return_value=_json_response(payload)) as post:
        publish_id, upload_url = _client().init_video_post(
            post_info={"title": "t", "privacy_level": "SELF_ONLY", "is_aigc": True},
            video_size=100,
            chunk_size=100,
            total_chunk_count=1,
        )
    assert publish_id == "v_pub~1"
    body = post.call_args.kwargs["json"]
    assert body["source_info"] == {
        "source": "FILE_UPLOAD",
        "video_size": 100,
        "chunk_size": 100,
        "total_chunk_count": 1,
    }


def test_upload_video_sends_content_range_per_chunk(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"a" * 25)
    chunks = [(0, 9), (10, 24)]  # 2 chunks, remainder folded
    put_resp = MagicMock(status_code=201, text="")
    with patch("tools.publishers.tiktok_client.requests.put", return_value=put_resp) as put:
        _client().upload_video("https://u", video, chunks)
    ranges = [c.kwargs["headers"]["Content-Range"] for c in put.call_args_list]
    assert ranges == ["bytes 0-9/25", "bytes 10-24/25"]
    assert put.call_args_list[0].kwargs["data"] == b"a" * 10
    assert put.call_args_list[1].kwargs["data"] == b"a" * 15


def test_upload_video_non_2xx_raises(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"a" * 10)
    put_resp = MagicMock(status_code=500, text="boom")
    with patch("tools.publishers.tiktok_client.requests.put", return_value=put_resp):
        with pytest.raises(TikTokAPIError):
            _client().upload_video("https://u", video, [(0, 9)])


def test_wait_for_publish_polls_until_complete():
    statuses = [
        {"data": {"status": "PROCESSING_UPLOAD"}, "error": {"code": "ok", "message": "", "log_id": ""}},
        {"data": {"status": "PUBLISH_COMPLETE"}, "error": {"code": "ok", "message": "", "log_id": ""}},
    ]
    with patch(
        "tools.publishers.tiktok_client.requests.post",
        side_effect=[_json_response(s) for s in statuses],
    ):
        final = _client().wait_for_publish("pid", timeout_sec=10, poll_interval_sec=0)
    assert final == "PUBLISH_COMPLETE"


def test_wait_for_publish_returns_failed():
    payload = {"data": {"status": "FAILED", "fail_reason": "bad"}, "error": {"code": "ok", "message": "", "log_id": ""}}
    with patch("tools.publishers.tiktok_client.requests.post", return_value=_json_response(payload)):
        final = _client().wait_for_publish("pid", timeout_sec=10, poll_interval_sec=0)
    assert final == "FAILED"


def test_exchange_code_sends_authorization_code_grant():
    payload = {"access_token": "at", "refresh_token": "rt", "open_id": "oid", "expires_in": 86400}
    with patch("tools.publishers.tiktok_client.requests.post", return_value=_json_response(payload)) as post:
        tokens = exchange_code("key", "secret", "the_code", "https://cb.example/callback/")
    assert tokens.access_token == "at"
    sent = post.call_args.kwargs["data"]
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "the_code"
    assert sent["redirect_uri"] == "https://cb.example/callback/"
