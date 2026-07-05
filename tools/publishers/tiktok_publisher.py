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
    determinism = Determinism.STOCHASTIC
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
