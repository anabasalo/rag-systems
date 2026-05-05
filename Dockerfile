# syntax=docker/dockerfile:1.7
#
# rag-systems — single-service container.
#
# Stage 1 builds the wheels (so ``pip install`` is cached separately
# from the application code). Stage 2 is a slim runtime image.
#
# Build:    docker build -t rag-systems .
# Run:      docker run --rm -p 8000:8000 --env-file .env rag-systems
# Compose:  docker compose up --build

# --- Stage 1: install Python dependencies -----------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Build deps for sentence-transformers / pdfplumber wheels.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


# --- Stage 2: runtime -------------------------------------------------
FROM python:3.12-slim

WORKDIR /app

# Copy pre-built wheels and install. No build toolchain in the runtime image.
COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
 && rm -rf /wheels

# Application code and shipped data (eval set, sample doc).
COPY app ./app
COPY data ./data

# Persistent paths used at runtime. The compose file mounts host
# volumes over these so state survives container restarts.
RUN mkdir -p /app/data/chroma /app/logs /app/.cache/huggingface
ENV HF_HOME=/app/.cache/huggingface \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# uvicorn for the API, single worker. The HF model is loaded on first
# request, not on startup, so cold start stays under a couple of seconds.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
