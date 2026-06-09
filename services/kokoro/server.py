import io
import os

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from kokoro_onnx import Kokoro
from pydantic import BaseModel

app = FastAPI(title="Kokoro TTS Service")

MODELS_DIR = os.getenv("MODELS_DIR", "/app/models")
ONNX_PATH = os.path.join(MODELS_DIR, "kokoro-v1.0.onnx")
VOICES_PATH = os.path.join(MODELS_DIR, "voices-v1.0.bin")

_kokoro: Kokoro | None = None


@app.on_event("startup")
def load_model():
    global _kokoro
    if not os.path.exists(ONNX_PATH) or not os.path.exists(VOICES_PATH):
        raise RuntimeError(
            f"Kokoro model files not found in {MODELS_DIR}. "
            "Run `python download_models.py` first."
        )
    _kokoro = Kokoro(ONNX_PATH, VOICES_PATH)


class TTSRequest(BaseModel):
    text: str
    voice: str = "af_heart"
    language: str = "en-us"
    speed: float = 1.0


@app.post("/tts")
async def synthesize(request: TTSRequest) -> Response:
    if _kokoro is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    samples, sample_rate = _kokoro.create(
        text=request.text,
        voice=request.voice,
        speed=request.speed,
        lang=request.language,
    )

    # PCM_16 required by LiveAvatar (16-bit, 24 kHz)
    samples_int16 = (np.array(samples) * 32767).clip(-32768, 32767).astype(np.int16)
    buffer = io.BytesIO()
    sf.write(buffer, samples_int16, sample_rate, format="WAV", subtype="PCM_16")
    buffer.seek(0)
    return Response(content=buffer.read(), media_type="audio/wav")


@app.get("/voices")
async def list_voices():
    """Return available voices from the loaded model."""
    if _kokoro is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"voices": _kokoro.get_voices()}


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": _kokoro is not None}
