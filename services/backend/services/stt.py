import asyncio
import logging
import os
import subprocess
import tempfile

import httpx

from core.config import settings

log = logging.getLogger(__name__)

_FFMPEG_TIMEOUT = 60
_MIN_AUDIO_BYTES = 44  # absolute minimum for a valid WAV header


class AudioConversionError(ValueError):
    """Raised when ffmpeg cannot process the raw audio blob."""


def _convert_to_wav(audio_bytes: bytes) -> bytes:
    if not audio_bytes or len(audio_bytes) < _MIN_AUDIO_BYTES:
        raise AudioConversionError(
            f"Audio blob too small ({len(audio_bytes)} bytes) — "
            "the recording may be empty or the microphone was not detected."
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        # Don't use an extension — let ffmpeg auto-detect format from magic bytes.
        # Safari records audio/mp4 (AAC), Chrome/Firefox use audio/webm (Opus).
        input_path = os.path.join(temp_dir, "input")
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
        except subprocess.CalledProcessError as exc:
            raise AudioConversionError(
                f"ffmpeg failed (exit {exc.returncode}): "
                f"{exc.stderr.decode(errors='replace')[:200]}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AudioConversionError(
                f"ffmpeg timed out after {_FFMPEG_TIMEOUT}s"
            ) from exc

        with open(output_path, "rb") as output_file:
            return output_file.read()


_MIN_AUDIO_BYTES_DIRECT = 128  # minimum raw bytes before sending to Whisper


async def transcribe(audio_bytes: bytes, language: str | None = None) -> str:
    """Send audio directly to Whisper (letting it handle ffmpeg conversion)."""
    if not audio_bytes or len(audio_bytes) < _MIN_AUDIO_BYTES_DIRECT:
        log.warning("Audio too small (%d bytes), skipping transcription", len(audio_bytes) if audio_bytes else 0)
        return ""

    params: dict = {"task": "transcribe", "output": "txt", "encode": "true"}
    if language:
        params["language"] = language

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{settings.whisper_url}/asr",
            files={"audio_file": ("audio.webm", audio_bytes, "application/octet-stream")},
            params=params,
        )
        response.raise_for_status()
        return response.text.strip()
