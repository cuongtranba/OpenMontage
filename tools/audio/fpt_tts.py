"""FPT.AI text-to-speech provider tool (Vietnamese-native voices)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

VOICES = {
    "banmai": {"gender": "female", "accent": "northern"},
    "thuminh": {"gender": "female", "accent": "northern"},
    "myan": {"gender": "female", "accent": "central"},
    "lannhi": {"gender": "female", "accent": "southern"},
    "linhsan": {"gender": "female", "accent": "southern"},
    "leminh": {"gender": "male", "accent": "northern"},
    "giahuy": {"gender": "male", "accent": "central"},
    "minhquang": {"gender": "male", "accent": "southern"},
}


class FPTTTS(BaseTool):
    name = "fpt_tts"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "fpt"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Set the FPT_TTS_API_KEY environment variable:\n"
        "  export FPT_TTS_API_KEY=your_key_here\n"
        "Get a key at https://fpt.ai/ (Speech Synthesis product)"
    )
    fallback = "elevenlabs_tts"
    fallback_tools = ["elevenlabs_tts", "openai_tts"]
    agent_skills = ["text-to-speech"]

    capabilities = ["text_to_speech", "voice_selection"]
    supports = {
        "voice_cloning": False,
        "multilingual": False,
        "offline": False,
        "native_audio": True,
    }
    best_for = [
        "native Vietnamese narration (8 regional voices)",
        "Vietnamese-language marketing and explainer videos",
    ]
    not_good_for = [
        "non-Vietnamese content",
        "SSML or fine-grained prosody control",
    ]

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string", "description": "Vietnamese text to synthesize (max 5000 chars)"},
            "voice_id": {
                "type": "string",
                "default": "banmai",
                "enum": sorted(VOICES),
                "description": "FPT voice name. Female: banmai/thuminh (north), myan (central), lannhi/linhsan (south). Male: leminh (north), giahuy (central), minhquang (south).",
            },
            "speed": {
                "type": "number",
                "default": 0,
                "minimum": -3,
                "maximum": 3,
                "description": "Speech rate offset, -3 (slowest) to 3 (fastest); 0 is normal",
            },
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=20, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["text", "voice_id", "speed"]
    side_effects = ["writes audio file to output_path", "calls FPT.AI API"]
    user_visible_verification = ["Listen to generated audio for natural Vietnamese speech"]

    API_URL = "https://api.fpt.ai/hmi/tts/v5"
    POLL_INTERVAL_SECONDS = 1.5
    POLL_TIMEOUT_SECONDS = 60

    def get_status(self) -> ToolStatus:
        if os.environ.get("FPT_TTS_API_KEY"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        # Free tier covers typical short-video narration volumes.
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        api_key = os.environ.get("FPT_TTS_API_KEY")
        if not api_key:
            return ToolResult(success=False, error="No FPT.AI API key. " + self.install_instructions)

        text = inputs.get("text", "")
        if not text.strip():
            return ToolResult(success=False, error="text is required")
        if len(text) > 5000:
            return ToolResult(success=False, error="FPT TTS v5 accepts at most 5000 characters per request")

        start = time.time()
        try:
            result = self._generate(inputs, api_key)
        except Exception as exc:
            return ToolResult(success=False, error=f"TTS generation failed: {exc}")

        result.duration_seconds = round(time.time() - start, 2)
        result.cost_usd = self.estimate_cost(inputs)
        return result

    def _generate(self, inputs: dict[str, Any], api_key: str) -> ToolResult:
        import requests

        voice = inputs.get("voice_id") or inputs.get("voice") or "banmai"
        if voice not in VOICES:
            return ToolResult(
                success=False,
                error=f"Unknown FPT voice '{voice}'. Valid voices: {', '.join(sorted(VOICES))}",
            )
        speed = inputs.get("speed", 0)

        response = requests.post(
            self.API_URL,
            headers={
                "api-key": api_key,
                "voice": voice,
                "speed": str(int(speed)),
                "Content-Type": "text/plain",
            },
            data=inputs["text"].encode("utf-8"),
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error") not in (0, "0", None):
            return ToolResult(success=False, error=f"FPT API error: {payload}")
        audio_url = payload.get("async")
        if not audio_url:
            return ToolResult(success=False, error=f"FPT API returned no audio URL: {payload}")

        audio_bytes = self._poll_audio(audio_url)
        if audio_bytes is None:
            return ToolResult(
                success=False,
                error=f"Audio not ready after {self.POLL_TIMEOUT_SECONDS}s at {audio_url}",
            )

        output_path = Path(inputs.get("output_path", "tts_output.mp3"))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)

        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "voice_id": voice,
                "voice_meta": VOICES[voice],
                "speed": speed,
                "text_length": len(inputs["text"]),
                "output": str(output_path),
                "audio_url": audio_url,
            },
            artifacts=[str(output_path)],
            model="fpt-tts-v5",
        )

    def _poll_audio(self, url: str) -> bytes | None:
        import requests

        deadline = time.time() + self.POLL_TIMEOUT_SECONDS
        while time.time() < deadline:
            resp = requests.get(url, timeout=30)
            # FPT serves 404 (or an HTML error page) until the file is rendered.
            if resp.status_code == 200 and resp.content[:3] != b"<!D" and len(resp.content) > 1000:
                return resp.content
            time.sleep(self.POLL_INTERVAL_SECONDS)
        return None
