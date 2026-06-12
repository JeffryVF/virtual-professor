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
