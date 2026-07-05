"""Typed client for the TikTok Content Posting API (Direct Post).

BaseTool-free so both the publisher tool and the interactive login script can
use it, and so it unit-tests with mocked HTTP. Validated live against the
sandbox API on 2026-07-05 (see docs/superpowers/specs/2026-07-05-tiktok-publisher-design.md).
"""

from __future__ import annotations

import json
import os
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
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(self), indent=2))
        path.chmod(0o600)  # ensure mode even if the file pre-existed

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
