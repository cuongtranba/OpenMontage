# TikTok Publisher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Post a finished render directly to the user's TikTok account at the human-approved `publish` stage, via the official Content Posting API (Direct Post, FILE_UPLOAD).

**Architecture:** A typed, BaseTool-free client module (`tiktok_client.py`) owns tokens + HTTP; a headless `TikTokPublisher(BaseTool)` tool wraps it for the registry/pipelines; a one-time interactive `scripts/tiktok_login.py` performs browser OAuth (user fronts the localhost listener with their own domain — we manage no tunnel). All 11 pipelines with a `publish` stage get `tiktok_publisher` in `tools_available`.

**Tech Stack:** Python 3.10+, `requests`, pytest (mocked HTTP — no live API calls), existing `tools/base_tool.py` contract, `schemas/artifacts/publish_log.schema.json`.

**Spec:** `docs/superpowers/specs/2026-07-05-tiktok-publisher-design.md` (read it first).

## Global Constraints

- Work in worktree `.worktrees/tiktok-probe`, branch `feat/tiktok-publisher`. Never commit to main.
- Run tests via `python3 -m pytest tests/tools/<file> -v` (targeted); full `make test` only once at the end.
- Strong typing everywhere: dataclasses, full signatures, no `Any` escape hatches except at JSON boundaries.
- Tool classes are PascalCase **without** "Tool" suffix; tools return `ToolResult` from `.execute(inputs: dict)`.
- Credentials come from env (`TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`) — never hardcode; tokens live at `~/.config/openmontage/tiktok_tokens.json`, mode 0600.
- `is_aigc: true` is ALWAYS sent — it is not an input.
- No live TikTok API calls in tests.

---

### Task 1: Client foundations — tokens, errors, chunk planning

**Files:**
- Create: `tools/publishers/tiktok_client.py`
- Test: `tests/tools/test_tiktok_client.py`

**Interfaces:**
- Produces (used by Tasks 2–4):
  - `TikTokTokens` dataclass: `access_token: str`, `refresh_token: str`, `open_id: str`, `expires_at: float`; methods `save(path: Path) -> None`, `TikTokTokens.load(path: Path) -> TikTokTokens`
  - `TikTokAuthError(Exception)`, `TikTokAPIError(Exception)` with attrs `code: str`, `message: str`, `log_id: str`
  - `plan_chunks(video_size: int, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[tuple[int, int]]` (inclusive byte ranges)
  - Constants: `API_BASE`, `TOKEN_URL`, `AUTH_URL`, `DEFAULT_TOKEN_PATH`, `DEFAULT_CHUNK_SIZE = 10 * 1024 * 1024`, `SCOPES = "user.info.basic,video.publish"`

- [ ] **Step 1: Write the failing tests**

```python
# tests/tools/test_tiktok_client.py
"""Tests for the TikTok client module (no live API calls)."""

import json
import os
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/cuong/repo/OpenMontage/.worktrees/tiktok-probe && python3 -m pytest tests/tools/test_tiktok_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.publishers.tiktok_client'`

- [ ] **Step 3: Write the implementation**

```python
# tools/publishers/tiktok_client.py
"""Typed client for the TikTok Content Posting API (Direct Post).

BaseTool-free so both the publisher tool and the interactive login script can
use it, and so it unit-tests with mocked HTTP. Validated live against the
sandbox API on 2026-07-05 (see docs/superpowers/specs/2026-07-05-tiktok-publisher-design.md).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

API_BASE = "https://open.tiktokapis.com/v2"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
SCOPES = "user.info.basic,video.publish"
DEFAULT_TOKEN_PATH = Path.home() / ".config" / "openmontage" / "tiktok_tokens.json"
DEFAULT_CHUNK_SIZE = 10 * 1024 * 1024
REFRESH_MARGIN_SEC = 300.0


class TikTokAuthError(Exception):
    """OAuth/token problems (missing, expired, refresh rejected)."""


class TikTokAPIError(Exception):
    """Non-ok error envelope from the Content Posting API."""

    def __init__(self, code: str, message: str, log_id: str = "") -> None:
        self.code = code
        self.message = message
        self.log_id = log_id
        super().__init__(f"{code}: {message}")


@dataclass
class TikTokTokens:
    access_token: str
    refresh_token: str
    open_id: str
    expires_at: float  # unix timestamp

    def save(self, path: Path = DEFAULT_TOKEN_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        path.chmod(0o600)

    @staticmethod
    def load(path: Path = DEFAULT_TOKEN_PATH) -> "TikTokTokens":
        return TikTokTokens(**json.loads(path.read_text(encoding="utf-8")))


def plan_chunks(
    video_size: int, chunk_size: int = DEFAULT_CHUNK_SIZE
) -> list[tuple[int, int]]:
    """Inclusive byte ranges per TikTok chunk rules.

    total_chunk_count = video_size // chunk_size; trailing bytes fold into the
    final chunk. Files <= chunk_size upload as a single chunk.
    """
    if video_size <= chunk_size:
        return [(0, video_size - 1)]
    count = video_size // chunk_size
    chunks = [(i * chunk_size, (i + 1) * chunk_size - 1) for i in range(count)]
    chunks[-1] = (chunks[-1][0], video_size - 1)
    return chunks
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/tools/test_tiktok_client.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add tools/publishers/tiktok_client.py tests/tools/test_tiktok_client.py
git commit -m "feat(publishers): TikTok client foundations — tokens, errors, chunk planning"
```

---

### Task 2: Client HTTP — token exchange/refresh, TokenStore, API calls

**Files:**
- Modify: `tools/publishers/tiktok_client.py` (append)
- Test: `tests/tools/test_tiktok_client.py` (append)

**Interfaces:**
- Consumes: Task 1 (`TikTokTokens`, errors, constants).
- Produces (used by Tasks 3–4):
  - `exchange_code(client_key: str, client_secret: str, code: str, redirect_uri: str) -> TikTokTokens`
  - `refresh_tokens(client_key: str, client_secret: str, refresh_token: str) -> TikTokTokens`
  - `class TokenStore: __init__(self, path: Path = DEFAULT_TOKEN_PATH)`, `exists(self) -> bool`, `fresh(self, client_key: str, client_secret: str) -> TikTokTokens`
  - `@dataclass CreatorInfo: username: str, nickname: str, privacy_level_options: list[str], max_video_post_duration_sec: int`
  - `class TikTokClient: __init__(self, tokens: TikTokTokens)`, `creator_info(self) -> CreatorInfo`, `init_video_post(self, post_info: dict[str, object], video_size: int, chunk_size: int, total_chunk_count: int) -> tuple[str, str]`, `upload_video(self, upload_url: str, video_path: Path, chunks: list[tuple[int, int]]) -> None`, `fetch_status(self, publish_id: str) -> dict[str, object]`, `wait_for_publish(self, publish_id: str, timeout_sec: float = 300.0, poll_interval_sec: float = 5.0) -> str`

- [ ] **Step 1: Write the failing tests (append to test file)**

```python
import time as _time
from unittest.mock import MagicMock, patch

from tools.publishers.tiktok_client import (
    CreatorInfo,
    TikTokAPIError,
    TikTokAuthError,
    TikTokClient,
    TokenStore,
    refresh_tokens,
)


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/tools/test_tiktok_client.py -v`
Expected: ImportError on `CreatorInfo` / `TikTokClient` / `TokenStore` / `refresh_tokens`

- [ ] **Step 3: Write the implementation (append to `tiktok_client.py`)**

```python
def _token_request(client_key: str, client_secret: str, form: dict[str, str]) -> TikTokTokens:
    form = {**form, "client_key": client_key, "client_secret": client_secret}
    resp = requests.post(
        TOKEN_URL,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    body = resp.json()
    if "access_token" not in body:
        raise TikTokAuthError(f"token endpoint returned {resp.status_code}: {body}")
    return TikTokTokens(
        access_token=str(body["access_token"]),
        refresh_token=str(body["refresh_token"]),
        open_id=str(body.get("open_id", "")),
        expires_at=time.time() + float(body.get("expires_in", 86400)),
    )


def exchange_code(
    client_key: str, client_secret: str, code: str, redirect_uri: str
) -> TikTokTokens:
    return _token_request(
        client_key,
        client_secret,
        {"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri},
    )


def refresh_tokens(client_key: str, client_secret: str, refresh_token: str) -> TikTokTokens:
    return _token_request(
        client_key,
        client_secret,
        {"grant_type": "refresh_token", "refresh_token": refresh_token},
    )


class TokenStore:
    """Loads saved tokens; auto-refreshes near expiry; persists rotated refresh tokens."""

    def __init__(self, path: Path = DEFAULT_TOKEN_PATH) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.is_file()

    def fresh(self, client_key: str, client_secret: str) -> TikTokTokens:
        if not self.exists():
            raise TikTokAuthError(
                f"No TikTok tokens at {self.path}. Run: python3 scripts/tiktok_login.py"
            )
        tokens = TikTokTokens.load(self.path)
        if time.time() < tokens.expires_at - REFRESH_MARGIN_SEC:
            return tokens
        tokens = refresh_tokens(client_key, client_secret, tokens.refresh_token)
        tokens.save(self.path)
        return tokens


@dataclass
class CreatorInfo:
    username: str
    nickname: str
    privacy_level_options: list[str]
    max_video_post_duration_sec: int


class TikTokClient:
    def __init__(self, tokens: TikTokTokens) -> None:
        self.tokens = tokens

    def _post(self, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        resp = requests.post(
            f"{API_BASE}{path}",
            json=payload if payload is not None else {},
            headers={
                "Authorization": f"Bearer {self.tokens.access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            timeout=30,
        )
        body: dict[str, object] = resp.json()
        error = body.get("error")
        if isinstance(error, dict) and error.get("code") not in ("ok", None):
            raise TikTokAPIError(
                code=str(error.get("code")),
                message=str(error.get("message", "")),
                log_id=str(error.get("log_id", "")),
            )
        return body

    def creator_info(self) -> CreatorInfo:
        body = self._post("/post/publish/creator_info/query/")
        data = body.get("data")
        assert isinstance(data, dict)
        return CreatorInfo(
            username=str(data.get("creator_username", "")),
            nickname=str(data.get("creator_nickname", "")),
            privacy_level_options=[str(o) for o in data.get("privacy_level_options", [])],
            max_video_post_duration_sec=int(data.get("max_video_post_duration_sec", 0)),
        )

    def init_video_post(
        self,
        post_info: dict[str, object],
        video_size: int,
        chunk_size: int,
        total_chunk_count: int,
    ) -> tuple[str, str]:
        body = self._post(
            "/post/publish/video/init/",
            {
                "post_info": post_info,
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": total_chunk_count,
                },
            },
        )
        data = body.get("data")
        assert isinstance(data, dict)
        return str(data["publish_id"]), str(data["upload_url"])

    def upload_video(
        self, upload_url: str, video_path: Path, chunks: list[tuple[int, int]]
    ) -> None:
        total = video_path.stat().st_size
        with open(video_path, "rb") as fh:
            for start, end in chunks:
                fh.seek(start)
                blob = fh.read(end - start + 1)
                resp = requests.put(
                    upload_url,
                    data=blob,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(blob)),
                        "Content-Range": f"bytes {start}-{end}/{total}",
                    },
                    timeout=600,
                )
                if resp.status_code not in (200, 201, 206):
                    raise TikTokAPIError(
                        code="upload_failed",
                        message=f"chunk {start}-{end} got HTTP {resp.status_code}: {resp.text[:300]}",
                    )

    def fetch_status(self, publish_id: str) -> dict[str, object]:
        body = self._post("/post/publish/status/fetch/", {"publish_id": publish_id})
        data = body.get("data")
        assert isinstance(data, dict)
        return data

    def wait_for_publish(
        self,
        publish_id: str,
        timeout_sec: float = 300.0,
        poll_interval_sec: float = 5.0,
    ) -> str:
        deadline = time.time() + timeout_sec
        while True:
            data = self.fetch_status(publish_id)
            status = str(data.get("status", ""))
            if status in ("PUBLISH_COMPLETE", "FAILED"):
                return status
            if time.time() >= deadline:
                return status or "TIMEOUT"
            time.sleep(poll_interval_sec)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/tools/test_tiktok_client.py -v`
Expected: 18 passed

- [ ] **Step 5: Commit**

```bash
git add tools/publishers/tiktok_client.py tests/tools/test_tiktok_client.py
git commit -m "feat(publishers): TikTok client HTTP — token refresh, creator info, chunked upload, status poll"
```

---

### Task 3: TikTokPublisher BaseTool

**Files:**
- Create: `tools/publishers/tiktok_publisher.py`
- Test: `tests/tools/test_tiktok_publisher.py`

**Interfaces:**
- Consumes: everything from Tasks 1–2 (`TokenStore`, `TikTokClient`, `CreatorInfo`, `plan_chunks`, `TikTokAPIError`, `TikTokAuthError`, `DEFAULT_CHUNK_SIZE`, `DEFAULT_TOKEN_PATH`).
- Produces: registry-discoverable tool `tiktok_publisher` returning `ToolResult` whose `data["publish_log"]` validates against `schemas/artifacts/publish_log`.

Follow `tools/publishers/export_bundle.py` for structure and metadata style. Key points the implementer must honor:

- Class `TikTokPublisher(BaseTool)`; `name = "tiktok_publisher"`; `tier = ToolTier.PUBLISH`; `capability = "publish"`; `provider = "tiktok"`; `stability = ToolStability.BETA`; `execution_mode = ExecutionMode.SYNC`; `determinism = Determinism.NONDETERMINISTIC`; `runtime = ToolRuntime.API`.
- `dependencies = ["env:TIKTOK_CLIENT_KEY", "env:TIKTOK_CLIENT_SECRET", "python:requests"]`.
- Override `check_dependencies()`: call `super().check_dependencies()` then raise `DependencyError` if `not TokenStore().exists()` with message pointing at `python3 scripts/tiktok_login.py`.
- `install_instructions = "1) Create a TikTok developer app with Login Kit + Content Posting API (scope video.publish). 2) Put TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET in .env.local. 3) Set TIKTOK_REDIRECT_URI to your registered HTTPS callback and point that domain at localhost. 4) Run: python3 scripts/tiktok_login.py"`.
- `supports = {"local_offline": False, "free": True, "uploads": True}`; `side_effects = ["posts a video to the connected TikTok account"]`.
- `user_visible_verification = ["Open the TikTok app/profile and confirm the video appears with the expected caption and privacy level"]`.
- Input schema: required `["video_path", "title", "privacy_level"]`; `privacy_level` enum `["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"]`; optional booleans `disable_comment`, `disable_duet`, `disable_stitch`; optional int `video_cover_timestamp_ms`; `title` maxLength 2200.
- Output schema: `{"publish_log": object, "publish_id": string, "creator_username": string}`.
- `is_aigc: True` always in `post_info`; never an input.
- Visibility mapping helper: `PUBLIC_TO_EVERYONE -> "public"`, `SELF_ONLY -> "private"`, else `"unlisted"`.
- Execute flow: validate file exists → `TokenStore().fresh(...)` → `creator_info()` → reject `privacy_level` not in `privacy_level_options` (before any upload) → `plan_chunks` → `init_video_post` → `upload_video` → `wait_for_publish` → build + schema-validate `publish_log` (import `validate_artifact` from `schemas.artifacts`, same as export_bundle) → `ToolResult(success=True, data=...)`.
- On `TikTokAuthError` / `TikTokAPIError`: return `ToolResult(success=False, error=str(exc), data={"publish_log": <failed entry log>})` where the failed entry is `{"platform": "tiktok", "status": "failed", "timestamp": <iso now>, "metadata_used": {"title": ..., "error": <code or message>}}` — also schema-validated.

- [ ] **Step 1: Write the failing tests**

```python
# tests/tools/test_tiktok_publisher.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/tools/test_tiktok_publisher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.publishers.tiktok_publisher'`

- [ ] **Step 3: Write the implementation**

```python
# tools/publishers/tiktok_publisher.py
"""Direct-post publisher for TikTok via the official Content Posting API.

Headless: requires a one-time interactive login (scripts/tiktok_login.py) that
saves a refresh token (valid 365 days). Unaudited/sandbox TikTok apps can only
post SELF_ONLY / friends / followers — PUBLIC_TO_EVERYONE requires TikTok's app
audit. The publish-director must present creator_info.privacy_level_options at
the human approval gate before calling this tool.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    DependencyError,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)
from tools.publishers.tiktok_client import (
    DEFAULT_CHUNK_SIZE,
    TikTokAPIError,
    TikTokAuthError,
    TikTokClient,
    TokenStore,
    plan_chunks,
)

_VISIBILITY = {"PUBLIC_TO_EVERYONE": "public", "SELF_ONLY": "private"}


class TikTokPublisher(BaseTool):
    name = "tiktok_publisher"
    version = "0.1.0"
    tier = ToolTier.PUBLISH
    capability = "publish"
    provider = "tiktok"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.NONDETERMINISTIC
    runtime = ToolRuntime.API

    dependencies = ["env:TIKTOK_CLIENT_KEY", "env:TIKTOK_CLIENT_SECRET", "python:requests"]
    install_instructions = (
        "1) Create a TikTok developer app with Login Kit + Content Posting API "
        "(scope video.publish). 2) Put TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET in "
        ".env.local. 3) Set TIKTOK_REDIRECT_URI to your registered HTTPS callback "
        "and point that domain at localhost. 4) Run: python3 scripts/tiktok_login.py"
    )

    agent_skills = []

    capabilities = ["direct_post_video", "write_publish_log"]
    supports = {"local_offline": False, "free": True, "uploads": True}
    best_for = [
        "posting a finished render directly to the connected TikTok account",
        "short-form vertical video distribution after the publish gate",
    ]
    not_good_for = [
        "public posting from an unaudited TikTok app (only SELF_ONLY/friends/followers)",
        "batch posting beyond TikTok's ~15 posts/day per-creator cap",
    ]

    input_schema = {
        "type": "object",
        "required": ["video_path", "title", "privacy_level"],
        "properties": {
            "video_path": {"type": "string", "description": "Path to the final MP4 render."},
            "title": {
                "type": "string",
                "maxLength": 2200,
                "description": "Caption; #hashtags and @mentions inline.",
            },
            "privacy_level": {
                "type": "string",
                "enum": [
                    "PUBLIC_TO_EVERYONE",
                    "MUTUAL_FOLLOW_FRIENDS",
                    "FOLLOWER_OF_CREATOR",
                    "SELF_ONLY",
                ],
                "description": "Must be one of creator_info.privacy_level_options.",
            },
            "disable_comment": {"type": "boolean"},
            "disable_duet": {"type": "boolean"},
            "disable_stitch": {"type": "boolean"},
            "video_cover_timestamp_ms": {"type": "integer"},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "publish_log": {"type": "object"},
            "publish_id": {"type": "string"},
            "creator_username": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=0, network_required=True
    )
    side_effects = ["posts a video to the connected TikTok account"]
    user_visible_verification = [
        "Open the TikTok app/profile and confirm the video appears with the expected caption and privacy level",
    ]

    def check_dependencies(self) -> None:
        super().check_dependencies()
        if not TokenStore().exists():
            raise DependencyError(
                "TikTok account not connected (no saved tokens). " + self.install_instructions
            )

    # ---- Execution ----

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        video_path = Path(inputs["video_path"]).expanduser()
        if not video_path.is_file():
            return ToolResult(success=False, error=f"video_path not found: {video_path}")

        title: str = inputs["title"]
        privacy_level: str = inputs["privacy_level"]

        try:
            tokens = TokenStore().fresh(
                os.environ["TIKTOK_CLIENT_KEY"], os.environ["TIKTOK_CLIENT_SECRET"]
            )
            client = TikTokClient(tokens)

            creator = client.creator_info()
            if privacy_level not in creator.privacy_level_options:
                return ToolResult(
                    success=False,
                    error=(
                        f"privacy_level {privacy_level!r} not allowed for this account; "
                        f"allowed: {creator.privacy_level_options}. Unaudited TikTok apps "
                        "cannot post PUBLIC_TO_EVERYONE."
                    ),
                )

            size = video_path.stat().st_size
            chunks = plan_chunks(size)
            chunk_size = min(size, DEFAULT_CHUNK_SIZE)

            post_info: dict[str, Any] = {
                "title": title,
                "privacy_level": privacy_level,
                "is_aigc": True,
            }
            for key in ("disable_comment", "disable_duet", "disable_stitch", "video_cover_timestamp_ms"):
                if key in inputs:
                    post_info[key] = inputs[key]

            publish_id, upload_url = client.init_video_post(
                post_info=post_info,
                video_size=size,
                chunk_size=chunk_size,
                total_chunk_count=len(chunks),
            )
            client.upload_video(upload_url, video_path, chunks)
            final_status = client.wait_for_publish(publish_id)
        except (TikTokAuthError, TikTokAPIError) as exc:
            return ToolResult(
                success=False,
                error=str(exc),
                data={"publish_log": self._publish_log("failed", title, error=str(exc))},
            )

        if final_status != "PUBLISH_COMPLETE":
            return ToolResult(
                success=False,
                error=f"publish did not complete (status: {final_status})",
                data={"publish_log": self._publish_log("failed", title, error=final_status)},
            )

        publish_log = self._publish_log(
            "published",
            title,
            video_id=publish_id,
            visibility=_VISIBILITY.get(privacy_level, "unlisted"),
        )
        return ToolResult(
            success=True,
            data={
                "publish_log": publish_log,
                "publish_id": publish_id,
                "creator_username": creator.username,
            },
        )

    @staticmethod
    def _publish_log(
        status: str,
        title: str,
        video_id: str | None = None,
        visibility: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {"title": title}
        if error:
            metadata["error"] = error
        entry: dict[str, Any] = {
            "platform": "tiktok",
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata_used": metadata,
        }
        if video_id:
            entry["video_id"] = video_id
        if visibility:
            entry["visibility"] = visibility
        log = {"version": "1.0", "entries": [entry]}

        from schemas.artifacts import validate_artifact

        validate_artifact("publish_log", log)
        return log
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/tools/test_tiktok_publisher.py -v`
Expected: 8 passed. If `validate_artifact` rejects `metadata_used.error`, check the schema's `additionalProperties` for `metadata_used`; if it forbids extra keys, move the error string into `metadata_used.description` instead and update the test accordingly.

- [ ] **Step 5: Commit**

```bash
git add tools/publishers/tiktok_publisher.py tests/tools/test_tiktok_publisher.py
git commit -m "feat(publishers): tiktok_publisher tool — direct post at the publish gate"
```

---

### Task 4: Interactive login script (no tunnel management)

**Files:**
- Create: `scripts/tiktok_login.py`
- Delete: `scripts/tiktok_probe.py` (untracked probe, superseded — `rm` it)
- Test: `tests/tools/test_tiktok_client.py` (append one test for `exchange_code`)

**Interfaces:**
- Consumes: `exchange_code`, `refresh_tokens`, `TikTokTokens`, `TokenStore`, `AUTH_URL`, `SCOPES`, `DEFAULT_TOKEN_PATH`, `TikTokClient` from Tasks 1–2.
- Produces: CLI with three modes: default (login), `--status`, `--refresh`. Env contract: requires `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI`; optional `TIKTOK_CALLBACK_PORT` (default 8917).

- [ ] **Step 1: Write the failing test (append to `tests/tools/test_tiktok_client.py`)**

```python
def test_exchange_code_sends_authorization_code_grant():
    payload = {"access_token": "at", "refresh_token": "rt", "open_id": "oid", "expires_in": 86400}
    from tools.publishers.tiktok_client import exchange_code

    with patch("tools.publishers.tiktok_client.requests.post", return_value=_json_response(payload)) as post:
        tokens = exchange_code("key", "secret", "the_code", "https://cb.example/callback/")
    assert tokens.access_token == "at"
    sent = post.call_args.kwargs["data"]
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "the_code"
    assert sent["redirect_uri"] == "https://cb.example/callback/"
```

- [ ] **Step 2: Run test to verify it passes already (exchange_code exists from Task 2) — if it fails, fix the client, not the test**

Run: `python3 -m pytest tests/tools/test_tiktok_client.py::test_exchange_code_sends_authorization_code_grant -v`
Expected: PASS

- [ ] **Step 3: Write the login script**

```python
# scripts/tiktok_login.py
"""One-time interactive TikTok login for OpenMontage.

Prereqs (user-managed — this script runs NO tunnel):
  1. TikTok developer app with Login Kit + Content Posting API, scope video.publish.
  2. TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET in .env / .env.local.
  3. TIKTOK_REDIRECT_URI in .env.local — an HTTPS URL registered in the app's
     Login Kit settings (TikTok rejects localhost). Point that domain at this
     machine's callback port yourself (reverse proxy, tunnel, etc.).
  4. Optional TIKTOK_CALLBACK_PORT (default 8917) — the local port this script
     listens on and your domain forwards to.

Usage:
  python3 scripts/tiktok_login.py            # browser OAuth, saves tokens
  python3 scripts/tiktok_login.py --status   # show connected account + expiry
  python3 scripts/tiktok_login.py --refresh  # force a token refresh
"""

from __future__ import annotations

import argparse
import http.server
import os
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import tools.base_tool  # noqa: E402,F401  (importing runs the dotenv loader)
from tools.publishers.tiktok_client import (  # noqa: E402
    AUTH_URL,
    DEFAULT_TOKEN_PATH,
    SCOPES,
    TikTokClient,
    TikTokTokens,
    TokenStore,
    exchange_code,
    refresh_tokens,
)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"{name} is not set — add it to .env.local")
    return value


def _login(client_key: str, client_secret: str) -> None:
    redirect_uri = _require_env("TIKTOK_REDIRECT_URI")
    port = int(os.environ.get("TIKTOK_CALLBACK_PORT", "8917"))
    state = secrets.token_urlsafe(16)
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            is_callback = parsed.path.rstrip("/").endswith("callback") and "code" in params
            if is_callback:
                result["code"] = params.get("code", [""])[0]
                result["state"] = params.get("state", [""])[0]
                result["error"] = params.get("error", [""])[0]
            self.send_response(200 if is_callback else 404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if is_callback:
                self.wfile.write(
                    b"<h2>OpenMontage: TikTok auth received. You can close this tab.</h2>"
                )

        def do_HEAD(self) -> None:  # noqa: N802
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    query = urllib.parse.urlencode(
        {
            "client_key": client_key,
            "scope": SCOPES,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    url = f"{AUTH_URL}?{query}"
    print(
        f"Listening on 127.0.0.1:{port} — make sure {redirect_uri} forwards here.\n"
        f"Open this URL in your browser (trying to auto-open):\n\n  {url}\n"
    )
    webbrowser.open(url)

    deadline = time.time() + 300
    while "code" not in result and time.time() < deadline:
        time.sleep(0.5)
    server.shutdown()

    if result.get("error"):
        sys.exit(f"Authorization denied: {result['error']}")
    if not result.get("code"):
        sys.exit("Timed out waiting for OAuth callback (5 min).")
    if result.get("state") != state:
        sys.exit("State mismatch — aborting (possible CSRF).")

    tokens = exchange_code(
        client_key, client_secret, urllib.parse.unquote(result["code"]), redirect_uri
    )
    tokens.save()
    creator = TikTokClient(tokens).creator_info()
    print(f"Connected as @{creator.username}. Tokens saved to {DEFAULT_TOKEN_PATH}")


def _status() -> None:
    store = TokenStore()
    if not store.exists():
        sys.exit(f"Not connected — no tokens at {DEFAULT_TOKEN_PATH}")
    tokens = TikTokTokens.load(store.path)
    remaining = tokens.expires_at - time.time()
    creator = TikTokClient(tokens).creator_info() if remaining > 0 else None
    who = f"@{creator.username}" if creator else "(access token expired — run --refresh)"
    print(f"Connected: {who}\nAccess token expires in {remaining / 3600:.1f}h")


def _refresh(client_key: str, client_secret: str) -> None:
    store = TokenStore()
    if not store.exists():
        sys.exit(f"Not connected — no tokens at {DEFAULT_TOKEN_PATH}")
    tokens = refresh_tokens(
        client_key, client_secret, TikTokTokens.load(store.path).refresh_token
    )
    tokens.save(store.path)
    print(f"Refreshed. New access token valid until {time.ctime(tokens.expires_at)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="One-time TikTok login for OpenMontage")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    if args.status:
        _status()
        return

    client_key = _require_env("TIKTOK_CLIENT_KEY")
    client_secret = _require_env("TIKTOK_CLIENT_SECRET")
    if args.refresh:
        _refresh(client_key, client_secret)
    else:
        _login(client_key, client_secret)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Smoke-check and remove the superseded probe**

```bash
python3 scripts/tiktok_login.py --help          # prints usage, exit 0
python3 scripts/tiktok_login.py --status        # "Connected: @..." (tokens exist from the probe session)
rm -f scripts/tiktok_probe.py                   # untracked probe, superseded
```

Expected: `--help` shows the three modes; `--status` prints the connected account.

- [ ] **Step 5: Commit**

```bash
git add scripts/tiktok_login.py tests/tools/test_tiktok_client.py
git commit -m "feat(scripts): one-time TikTok OAuth login (user-fronted callback, no tunnel)"
```

---

### Task 5: Pipeline wiring + publish-director guidance + full verification

**Files:**
- Modify: the `publish` stage `tools_available` line in all 11 manifests:
  `pipeline_defs/animated-explainer.yaml`, `animation.yaml`, `avatar-spokesperson.yaml`, `character-animation.yaml`, `cinematic.yaml`, `clip-factory.yaml`, `hybrid.yaml`, `localization-dub.yaml`, `podcast-repurpose.yaml`, `screen-demo.yaml`, `talking-head.yaml`
- Modify: each pipeline's publish-director skill `skills/pipelines/<pipeline>/publish-director.md` (11 files — locate with `ls skills/pipelines/*/publish-director.md`)
- Test: `tests/contracts/` manifest validation (existing suite) + full `make test`

- [ ] **Step 1: Wire the tool into every publish stage**

For `animated-explainer.yaml` change `tools_available: [export_bundle]` → `tools_available: [export_bundle, tiktok_publisher]`. For the other 10, in the `publish` stage only, change `tools_available: []` → `tools_available: [tiktok_publisher]`.

Verify:

```bash
for f in pipeline_defs/*.yaml; do awk '/^  - name: publish/{found=1} found && /tools_available/{print FILENAME": "$0; found=0}' "$f"; done
```

Expected: all 11 lines contain `tiktok_publisher`.

- [ ] **Step 2: Add TikTok guidance to each publish-director skill**

Append this section verbatim to each `skills/pipelines/<pipeline>/publish-director.md` (adjusting nothing per pipeline):

```markdown
## TikTok Direct Post (tiktok_publisher)

When the brief targets TikTok and `tiktok_publisher` is AVAILABLE in the registry:

1. Call `creator_info` first (the tool does this internally, but for the approval gate run it via the tool's client or a dry run) and present the REAL `privacy_level_options` to the user. Never assume `PUBLIC_TO_EVERYONE` — unaudited TikTok apps can only post `SELF_ONLY` / friends / followers.
2. At the publish checkpoint present: the final video path, the exact caption (`title`, hashtags inline, ≤2200 chars), and the privacy level choice. Wait for approval — this gate is `human_approval_default: true`.
3. Log the decision in `decision_log` (`category: "publish_target"`, subject: "TikTok direct post") with privacy level and caption.
4. After approval call `tiktok_publisher` with `video_path`, `title`, `privacy_level`. The tool always labels the post as AI-generated content (`is_aigc`).
5. Merge the returned `publish_log` entries with any `export_bundle` entries into the stage's canonical `publish_log` artifact.
6. Mind the platform caps: ~15 posts/day per creator, 6 API requests/min — relevant for clip-factory batch runs.

If the tool is UNAVAILABLE, offer the setup path from its `install_instructions` (env keys + `python3 scripts/tiktok_login.py`) instead of silently exporting only.
```

- [ ] **Step 3: Run manifest contract tests**

Run: `python3 -m pytest tests/contracts/ -v`
Expected: PASS (manifests still schema-valid)

- [ ] **Step 4: Full verification (sequential, once)**

```bash
make test
```

Expected: full suite passes, including the new `test_tiktok_client.py` and `test_tiktok_publisher.py`.

Also verify registry discovery end-to-end:

```bash
python3 -c "
from tools.tool_registry import registry
registry.discover()
t = registry._tools['tiktok_publisher']
print(t.get_status().value, t.get_info()['capability'])
"
```

Expected: `available publish` (tokens + env exist on this machine).

- [ ] **Step 5: Commit**

```bash
git add pipeline_defs/ skills/pipelines/
git commit -m "feat(pipelines): wire tiktok_publisher into every publish stage + director guidance"
```

---

## Self-Review Notes

- Spec coverage: client module (T1–T2), tool (T3), login script (T4), manifest wiring + director guidance (T5), tests throughout — all spec sections covered. ffprobe duration check from the spec is intentionally DROPPED: `creator_info.max_video_post_duration_sec` is 3600s and TikTok rejects overlong videos server-side with a clear error; a local ffprobe pre-check adds a `cmd:ffprobe` dependency for marginal value (YAGNI). Spec deviation accepted.
- Type consistency: `plan_chunks` returns inclusive `(start, end)` tuples consumed by `upload_video`; `TokenStore.fresh(client_key, client_secret)` signature consistent across T2/T3/T4.
- No placeholders: every step has full code or exact commands.
