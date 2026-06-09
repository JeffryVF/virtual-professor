import asyncio
import logging
import os
import subprocess
import tempfile

import httpx

from core.config import settings

log = logging.getLogger(__name__)

_FFMPEG_TIMEOUT = 60


def _convert_to_wav(audio_bytes: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = os.path.join(temp_dir, "input.webm")
        output_path = os.path.join(temp_dir, "output.wav")

        with open(input_path, "wb") as input_file:
            input_file.write(audio_bytes)

        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    input_path,
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    output_path,
                ],
                check=True,
                capture_output=True,
                timeout=_FFMPEG_TIMEOUT,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("ffmpeg not found") from exc

        with open(output_path, "rb") as output_file:
            return output_file.read()


async def transcribe(audio_bytes: bytes, language: str | None = None) -> str:
    """Send audio to Whisper and return the transcript text."""
    params: dict = {"task": "transcribe", "output": "txt"}
    if language:
        params["language"] = language

    wav_bytes = await asyncio.to_thread(_convert_to_wav, audio_bytes)

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{settings.whisper_url}/asr",
            files={"audio_file": ("audio.wav", wav_bytes, "audio/wav")},
            params=params,
        )
        response.raise_for_status()
        return response.text.strip()
