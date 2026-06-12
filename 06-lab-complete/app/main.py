"""
DrugLaw RAG Agent — Production FastAPI

Day 8 RAG chatbot (luật ma tuý Việt Nam) productionized với Day 12 patterns:
  ✅ Config từ environment (12-factor)
  ✅ Structured JSON logging
  ✅ API Key authentication
  ✅ Rate limiting (10 req/min per user)
  ✅ Cost guard ($10/month per user)
  ✅ Health check + Readiness probe
  ✅ Graceful shutdown (SIGTERM)
  ✅ Stateless: conversation history in Redis
  ✅ Security headers
  ✅ CORS
"""
import sys
import time
import signal
import logging
import json
from pathlib import Path
from datetime import datetime, timezone
from contextlib import asynccontextmanager

# Đảm bảo src/ được tìm thấy khi chạy từ /app trong container
sys.path.insert(0, str(Path(__file__).parent.parent))

import redis as redis_module
from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from app.config import settings
from app.auth import verify_api_key
from app.rate_limiter import check_rate_limit
from app.cost_guard import check_budget, record_usage, get_usage

# ─────────────────────────────────────────────────────────
# Logging — JSON structured
# ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='{"ts":"%(asctime)s","lvl":"%(levelname)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)

START_TIME = time.time()
_is_ready = False
_request_count = 0
_error_count = 0

# ─────────────────────────────────────────────────────────
# RAG Supervisor (lazy init — nặng, chỉ load 1 lần)
# ─────────────────────────────────────────────────────────
_supervisor = None


def get_supervisor():
    global _supervisor
    if _supervisor is None:
        from src.agent.supervisor import Supervisor
        _supervisor = Supervisor()
        logger.info(json.dumps({"event": "supervisor_loaded"}))
    return _supervisor


# ─────────────────────────────────────────────────────────
# Redis — optional, graceful fallback
# ─────────────────────────────────────────────────────────
_redis_client = None


def get_redis():
    global _redis_client
    if not settings.redis_url:
        return None
    try:
        if _redis_client is None:
            _redis_client = redis_module.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
            )
        _redis_client.ping()
        return _redis_client
    except Exception:
        return None


# ─────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready
    logger.info(json.dumps({
        "event": "startup",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }))

    # Pre-load RAG supervisor để request đầu tiên không bị chậm
    try:
        get_supervisor()
        logger.info(json.dumps({"event": "rag_pipeline_ready"}))
    except Exception as e:
        logger.error(json.dumps({"event": "rag_pipeline_error", "error": str(e)}))

    r = get_redis()
    logger.info(json.dumps({
        "event": "redis_status",
        "connected": r is not None,
    }))

    _is_ready = True
    logger.info(json.dumps({"event": "ready"}))

    yield

    _is_ready = False
    logger.info(json.dumps({"event": "shutdown"}))


# ─────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="RAG chatbot về pháp luật ma tuý Việt Nam và tin tức nghệ sĩ liên quan.",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    global _request_count, _error_count
    start = time.time()
    _request_count += 1
    try:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers.pop("server", None)
        duration = round((time.time() - start) * 1000, 1)
        logger.info(json.dumps({
            "event": "request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": duration,
        }))
        return response
    except Exception:
        _error_count += 1
        raise


# ─────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000,
                          description="Câu hỏi về luật ma tuý hoặc tin tức nghệ sĩ")
    user_id: str = Field(default="anonymous", max_length=64,
                         description="User ID để track lịch sử và budget")
    top_k: int = Field(default=5, ge=1, le=10,
                       description="Số chunks tối đa đưa vào context")


class SourceDoc(BaseModel):
    content: str
    score: float
    source: str
    doc_type: str


class AskResponse(BaseModel):
    question: str
    answer: str
    sources: list[SourceDoc]
    retrieval_source: str
    user_id: str
    timestamp: str


# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────

@app.get("/", tags=["Info"])
def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "description": "RAG chatbot — luật ma tuý Việt Nam & tin tức nghệ sĩ",
        "endpoints": {
            "ask": "POST /ask (requires X-API-Key)",
            "health": "GET /health",
            "ready": "GET /ready",
            "docs": "GET /docs (dev only)",
        },
    }


@app.post("/ask", response_model=AskResponse, tags=["Agent"])
async def ask_agent(
    body: AskRequest,
    request: Request,
    _key: str = Depends(verify_api_key),
):
    """
    Gửi câu hỏi về pháp luật ma tuý hoặc nghệ sĩ liên quan.

    **Authentication:** Header `X-API-Key: <your-key>`

    **Ví dụ câu hỏi:**
    - Hình phạt tàng trữ heroin theo Điều 249 là bao nhiêu năm tù?
    - Ca sĩ Chi Dân bị đề nghị truy tố về tội gì?
    - Luật Phòng chống ma tuý 2021 nghiêm cấm những hành vi nào?
    """
    # Rate limit per API key
    check_rate_limit(_key[:8])

    # Monthly budget check per user
    check_budget(body.user_id)

    # Load conversation history từ Redis (stateless design)
    r = get_redis()
    conversation_history = []
    if r:
        try:
            raw = r.lrange(f"history:{body.user_id}", -4, -1)
            conversation_history = [json.loads(h) for h in raw if h]
        except Exception:
            pass

    logger.info(json.dumps({
        "event": "rag_call",
        "user_id": body.user_id,
        "q_len": len(body.question),
        "top_k": body.top_k,
        "history_len": len(conversation_history),
        "client": str(request.client.host) if request.client else "unknown",
    }))

    # Gọi RAG Supervisor
    try:
        supervisor = get_supervisor()
        result = supervisor.run(
            query=body.question,
            top_k=body.top_k,
            conversation_history=conversation_history if conversation_history else None,
        )
    except Exception as e:
        logger.error(json.dumps({"event": "rag_error", "error": str(e)}))
        raise HTTPException(status_code=500, detail=f"RAG pipeline error: {str(e)}")

    answer = result.get("answer", "Không tìm thấy thông tin liên quan.")
    raw_sources = result.get("sources", [])
    retrieval_source = result.get("retrieval_source", "hybrid")

    # Record token usage (ước tính cho cost guard)
    input_tokens = len(body.question.split()) * 2
    output_tokens = len(answer.split()) * 2
    record_usage(body.user_id, input_tokens, output_tokens)

    # Lưu conversation history vào Redis
    if r:
        try:
            r.rpush(f"history:{body.user_id}",
                    json.dumps({"role": "user", "content": body.question}))
            r.rpush(f"history:{body.user_id}",
                    json.dumps({"role": "assistant", "content": answer[:500]}))
            r.expire(f"history:{body.user_id}", 86400)
        except Exception:
            pass

    # Format sources
    sources = []
    for s in raw_sources:
        meta = s.get("metadata", {})
        sources.append(SourceDoc(
            content=s.get("content", "")[:300],
            score=round(s.get("score", 0.0), 4),
            source=meta.get("source", "unknown"),
            doc_type=meta.get("type", "unknown"),
        ))

    return AskResponse(
        question=body.question,
        answer=answer,
        sources=sources,
        retrieval_source=retrieval_source,
        user_id=body.user_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/health", tags=["Operations"])
def health():
    """Liveness probe. Platform restarts container nếu fail."""
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Operations"])
def ready():
    """Readiness probe. Load balancer ngừng routing nếu not ready."""
    if not _is_ready:
        raise HTTPException(503, "Not ready — RAG pipeline initializing")
    return {"ready": True, "supervisor": _supervisor is not None}


@app.get("/metrics", tags=["Operations"])
def metrics(_key: str = Depends(verify_api_key)):
    """Metrics endpoint (protected)."""
    r = get_redis()
    return {
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "error_count": _error_count,
        "redis_connected": r is not None,
        "rag_loaded": _supervisor is not None,
        "monthly_budget_usd": settings.monthly_budget_usd,
        "rate_limit_per_minute": settings.rate_limit_per_minute,
    }


# ─────────────────────────────────────────────────────────
# Graceful Shutdown
# ─────────────────────────────────────────────────────────
def _handle_signal(signum, _frame):
    logger.info(json.dumps({"event": "signal", "signum": signum, "action": "graceful_shutdown"}))


signal.signal(signal.SIGTERM, _handle_signal)


if __name__ == "__main__":
    logger.info(f"Starting {settings.app_name} on {settings.host}:{settings.port}")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        timeout_graceful_shutdown=30,
    )
