FROM python:3.11-slim

WORKDIR /app

# Render Free = 512MB. Keep the process single-threaded and stop glibc from
# grabbing extra arenas. Embeddings are Gemini API calls (no local model).
ENV HF_HUB_DISABLE_TELEMETRY=1
ENV TOKENIZERS_PARALLELISM=false
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV ORT_INTRA_OP_NUM_THREADS=1
ENV MALLOC_ARENA_MAX=2
ENV WEB_CONCURRENCY=1

RUN apt-get update && apt-get install -y \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Do not install PyTorch / sentence-transformers / the BGE reranker.
# Those packages are optional locally (RERANKER_TYPE=bge). On Render they
# push RSS over 512MB as soon as a document is vectorized.
RUN grep -vE '^(torch|sentence-transformers|llama-index-postprocessor-sbert-rerank)' requirements.txt \
      > /tmp/requirements.prod.txt \
    && pip install --no-cache-dir -r /tmp/requirements.prod.txt

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers"]
