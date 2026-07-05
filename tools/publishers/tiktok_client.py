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
