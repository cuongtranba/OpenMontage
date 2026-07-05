"""Tests for the tiktok_publisher tool (mocked client — no live API)."""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from schemas.artifacts import validate_artifact
from tools.base_tool import DependencyError, ToolStatus
from tools.publishers.tiktok_client import CreatorInfo, TikTokAPIError, TikTokTokens
from tools.publishers.tiktok_publisher import TikTokPublisher


@pytest.fixture()
def env_keys(monkeypatch):
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "k")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "s")


@pytest.fixture()
def video(tmp_path) -> Path:
    p = tmp_path / "final.mp4"
    p.write_bytes(b"x" * 1024)
    return p


CREATOR = CreatorInfo(
    username="nevermind780",
    nickname="Never mind",
    privacy_level_options=["FOLLOWER_OF_CREATOR", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"],
    max_video_post_duration_sec=3600,
)


def _tokens() -> TikTokTokens:
    return TikTokTokens("at", "rt", "oid", time.time() + 3600)


def test_tool_metadata():
    tool = TikTokPublisher()
    info = tool.get_info()
    assert info["name"] == "tiktok_publisher"
    assert info["capability"] == "publish"
    assert info["provider"] == "tiktok"


def test_unavailable_without_env(monkeypatch):
    monkeypatch.delenv("TIKTOK_CLIENT_KEY", raising=False)
    monkeypatch.delenv("TIKTOK_CLIENT_SECRET", raising=False)
    assert TikTokPublisher().get_status() == ToolStatus.UNAVAILABLE


def test_unavailable_without_token_file(env_keys, tmp_path):
    with patch("tools.publishers.tiktok_publisher.TokenStore") as store_cls:
        store_cls.return_value.exists.return_value = False
        assert TikTokPublisher().get_status() == ToolStatus.UNAVAILABLE


def test_privacy_mismatch_fails_before_upload(env_keys, video):
    client = MagicMock()
    client.creator_info.return_value = CREATOR
    with patch("tools.publishers.tiktok_publisher.TokenStore") as store_cls, patch(
        "tools.publishers.tiktok_publisher.TikTokClient", return_value=client
    ):
        store_cls.return_value.fresh.return_value = _tokens()
        result = TikTokPublisher().execute(
            {"video_path": str(video), "title": "t", "privacy_level": "PUBLIC_TO_EVERYONE"}
        )
    assert result.success is False
    assert "privacy" in result.error.lower()
    client.init_video_post.assert_not_called()
    client.upload_video.assert_not_called()


def test_successful_post_returns_schema_valid_publish_log(env_keys, video):
    client = MagicMock()
    client.creator_info.return_value = CREATOR
    client.init_video_post.return_value = ("v_pub~42", "https://u")
    client.wait_for_publish.return_value = "PUBLISH_COMPLETE"
    with patch("tools.publishers.tiktok_publisher.TokenStore") as store_cls, patch(
        "tools.publishers.tiktok_publisher.TikTokClient", return_value=client
    ):
        store_cls.return_value.fresh.return_value = _tokens()
        result = TikTokPublisher().execute(
            {"video_path": str(video), "title": "My video #test", "privacy_level": "SELF_ONLY"}
        )
    assert result.success is True
    log = result.data["publish_log"]
    validate_artifact("publish_log", log)
    entry = log["entries"][0]
    assert entry["platform"] == "tiktok"
    assert entry["status"] == "published"
    assert entry["video_id"] == "v_pub~42"
    assert entry["visibility"] == "private"
    # is_aigc is always sent
    post_info = client.init_video_post.call_args.kwargs["post_info"]
    assert post_info["is_aigc"] is True


def test_api_error_maps_to_failed_publish_log(env_keys, video):
    client = MagicMock()
    client.creator_info.return_value = CREATOR
    client.init_video_post.side_effect = TikTokAPIError(
        "spam_risk_too_many_posts", "daily cap reached", "L1"
    )
    with patch("tools.publishers.tiktok_publisher.TokenStore") as store_cls, patch(
        "tools.publishers.tiktok_publisher.TikTokClient", return_value=client
    ):
        store_cls.return_value.fresh.return_value = _tokens()
        result = TikTokPublisher().execute(
            {"video_path": str(video), "title": "t", "privacy_level": "SELF_ONLY"}
        )
    assert result.success is False
    assert "spam_risk_too_many_posts" in result.error
    log = result.data["publish_log"]
    validate_artifact("publish_log", log)
    assert log["entries"][0]["status"] == "failed"


def test_missing_video_path_fails(env_keys):
    result = TikTokPublisher().execute(
        {"video_path": "/nonexistent/final.mp4", "title": "t", "privacy_level": "SELF_ONLY"}
    )
    assert result.success is False
    assert "not found" in result.error


def test_registry_discovers_tiktok_publisher():
    from tools.tool_registry import registry

    registry.discover()
    assert "tiktok_publisher" in registry._tools
