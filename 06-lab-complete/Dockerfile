# ============================================================
# DrugLaw RAG Agent — Production Dockerfile (Multi-stage)
#
# Stage 1 (builder): cài Python packages
# Stage 2 (runtime): chỉ copy packages + source code
# ============================================================

# ── Stage 1: Builder ──────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# gcc cần cho một số chromadb dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Cài CPU-only torch trước (nhỏ hơn GPU version ~600MB)
RUN pip install --no-cache-dir --user \
    torch --index-url https://download.pytorch.org/whl/cpu

# Cài toàn bộ dependencies
RUN pip install --no-cache-dir --user -r requirements.txt

# Pre-download embedding model vào image (tránh download lúc startup)
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); \
print('Model downloaded.')"


# ── Stage 2: Runtime ──────────────────────────────────────
FROM python:3.11-slim AS runtime

# Non-root user — security best practice
RUN groupadd -r agent && useradd -r -g agent -d /app agent

WORKDIR /app

# Copy packages từ builder (bao gồm cả HuggingFace model cache)
COPY --from=builder /root/.local /home/agent/.local

# Copy source code
COPY app/ ./app/
COPY src/ ./src/
COPY data/ ./data/

RUN chown -R agent:agent /app

USER agent

ENV PATH=/home/agent/.local/bin:$PATH
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Trỏ HuggingFace cache về thư mục đã copy
ENV HF_HOME=/home/agent/.local/share/huggingface
ENV TRANSFORMERS_CACHE=/home/agent/.local/share/huggingface/hub

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=15s --start-period=60s --retries=3 \
    CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
    || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
