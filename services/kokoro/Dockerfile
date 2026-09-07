FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Model files (kokoro-v0_19.onnx + voices.bin) must be present in /app/models
# Run download_models.py once before starting, or mount a pre-populated volume:
#   docker run --rm -v kokoro_models:/app/models virtual_profesor-kokoro python download_models.py
VOLUME ["/app/models"]

EXPOSE 8880

CMD ["sh", "-c", "python download_models.py && uvicorn server:app --host 0.0.0.0 --port ${PORT:-8880}"]
