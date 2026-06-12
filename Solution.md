# Day 12 Lab — Solution

**Student Name:** Le Quoc Anh  
**Student ID:** 2A202600824  
**Date:** 2026-06-12

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

1. **API key hardcode** — `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` — push lên GitHub là lộ key ngay.
2. **Database URL hardcode** — `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"` — chứa cả username/password.
3. **Debug mode bật cứng** — `DEBUG = True` và `reload=True` trong uvicorn — không bao giờ dùng trong production.
4. **Dùng `print()` thay vì logging** — không có log level, không filter được, không gửi vào log aggregator.
5. **Log ra secret** — `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` — key bị expose trong stdout/logs.
6. **Không có health check** — platform (Railway, K8s) không biết khi nào restart container.
7. **Port cứng 8000** — không đọc từ `PORT` env var, Railway/Render inject port qua env.
8. **Binding trên `localhost`** — container chỉ nghe nội bộ, không nhận traffic từ bên ngoài; phải dùng `0.0.0.0`.

### Exercise 1.3: So sánh Develop vs Production

| Feature | Develop | Production | Tại sao quan trọng? |
|---------|---------|------------|---------------------|
| Config | Hardcode trong code | Đọc từ env vars | Secrets không lộ, linh hoạt theo môi trường |
| Health check | Không có | `/health` + `/ready` | Platform tự động restart khi crash |
| Logging | `print()` | JSON structured | Dễ parse bởi Datadog/Loki, có log level |
| Host binding | `localhost` | `0.0.0.0` | Container phải nghe trên tất cả interfaces |
| Port | Hardcode `8000` | Từ `PORT` env var | Railway/Render inject port động |
| Debug/reload | Luôn bật | Chỉ khi `DEBUG=true` | reload gây chậm và lỗi production |
| Graceful shutdown | Không có | SIGTERM handler | Request đang xử lý không bị mất |
| CORS | Không có | Middleware configurable | Ngăn cross-origin không hợp lệ |

---

## Part 2: Docker

### Exercise 2.1: Câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` — full Python distribution (~1 GB).
2. **Working directory:** `/app`.
3. **Tại sao COPY requirements.txt trước?** Docker cache từng layer. `requirements.txt` ít thay đổi hơn code → layer install dependencies được cache lại, chỉ rebuild khi requirements thay đổi — tiết kiệm thời gian build đáng kể.
4. **CMD vs ENTRYPOINT:** `CMD` là default command, có thể override khi `docker run image <other-cmd>`. `ENTRYPOINT` là fixed executable, chỉ thêm arguments. Dùng `ENTRYPOINT` cho binary chính, `CMD` cho default arguments.

### Exercise 2.3: Multi-stage build

- **Stage 1 (builder):** Cài `gcc`, `libpq-dev`, rồi `pip install --user`. Cần build tools để compile native packages.
- **Stage 2 (runtime):** Bắt đầu từ `python:3.11-slim` sạch, chỉ copy `/root/.local` (packages đã compile). Không có gcc, apt cache, build tools → image nhỏ hơn nhiều.
- **Kết quả:** develop image ~1 GB → production image ~200-250 MB (giảm 75%).

### Exercise 2.4: Docker Compose stack

Services trong `02-docker/production/docker-compose.yml`:
- **nginx** — reverse proxy / load balancer, expose port 80
- **agent** — FastAPI app, scale nhiều instances
- **redis** — lưu state để stateless design

Communication: Client → Nginx (80) → Agent (8000, internal) → Redis (6379, internal).

---

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment steps

```bash
npm i -g @railway/cli
railway login
railway init
railway variables set PORT=8000
railway variables set GROQ_API_KEY=<key>
railway variables set AGENT_API_KEY=<key>
railway up
railway domain
```

### Exercise 3.2: So sánh `render.yaml` vs `railway.toml`

| | `railway.toml` | `render.yaml` |
|--|----------------|---------------|
| Format | TOML | YAML |
| Builder | `builder = "DOCKERFILE"` | `env: docker` |
| Health check | Auto từ Dockerfile | Khai báo `healthCheckPath` |
| Scaling | Dashboard / `railway scale` | `numInstances` trong yaml |
| Env vars | `railway variables set` | Dashboard (secrets) + yaml |

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication

- **Check ở đâu?** `verify_api_key()` dependency — inject qua `Depends()` vào endpoint.
- **Sai key:** 401 (missing) hoặc 403 (invalid).
- **Rotate key:** Đổi `AGENT_API_KEY` env var, restart service. Không sửa code.

### Exercise 4.2: JWT Flow

1. `POST /auth/token` với username/password → nhận JWT token (expire 60 phút).
2. Mọi request gửi `Authorization: Bearer <token>`.
3. Server decode JWT, verify signature + expiry, extract username + role.
4. Token hết hạn → đăng nhập lại.
5. **Lợi thế:** Stateless, tự expire, mang thêm role/claims.

### Exercise 4.3: Rate Limiting

- **Algorithm:** Sliding Window Counter — deque timestamps per user, loại bỏ > 60s.
- **Limit:** 10 req/phút per user.
- **HTTP 429** kèm `Retry-After: 60` header khi vượt limit.

### Exercise 4.4: Cost Guard

```python
def check_budget(user_id: str) -> None:
    record = _get_record(user_id)        # monthly record per user
    if record["cost"] >= monthly_budget: # $10/tháng
        raise HTTPException(402, "Monthly budget exceeded")

def record_usage(user_id, input_tokens, output_tokens) -> None:
    record["cost"] += (input_tokens/1000)*0.00015 + (output_tokens/1000)*0.0006
```

Track per-user, reset đầu tháng, raise HTTP 402 khi vượt $10.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health vs Readiness

```python
@app.get("/health")    # Liveness: process còn sống?
def health():
    return {"status": "ok"}

@app.get("/ready")     # Readiness: sẵn sàng nhận traffic?
def ready():
    if not _is_ready:
        raise HTTPException(503, "Not ready")
    return {"ready": True}
```

`/health` → platform restart nếu fail. `/ready` → load balancer stop routing nếu fail.

### Exercise 5.2: Graceful Shutdown

```python
signal.signal(signal.SIGTERM, handle_sigterm)
# uvicorn timeout_graceful_shutdown=30 — chờ in-flight requests hoàn thành
```

Khi platform gửi SIGTERM, server ngừng nhận request mới, hoàn thành request đang xử lý, rồi exit 0.

### Exercise 5.3: Stateless Design

```python
# ❌ In-memory — không scale được
conversation_history = {}

# ✅ Redis — tất cả instances đọc chung
r.lrange(f"history:{user_id}", -4, -1)
r.rpush(f"history:{user_id}", json.dumps({...}))
```

Khi scale ra 3 instances, mọi instance đều đọc/ghi cùng Redis → session không bị mất khi request vào instance khác.

### Exercise 5.4: Load Balancing

```bash
docker compose up --scale agent=3
```

Nginx phân tán request round-robin giữa 3 instances. Nếu 1 instance down → health check fail → Nginx ngừng route → zero downtime.

### Exercise 5.5: Stateless Test

`test_stateless.py` tạo conversation → kill 1 instance → tiếp tục conversation → history vẫn còn (vì lưu trong Redis, không trong instance bị kill).

---

## Part 6: Final Project — DrugLaw RAG Agent

Xem source code đầy đủ trong `06-lab-complete/`.

**Project:** Productionized RAG chatbot về pháp luật ma tuý Việt Nam (Day 8).

**Stack:**
- **RAG Pipeline:** ChromaDB + BM25 + RRF reranking + Groq Llama-3.1-8b
- **API:** FastAPI với auth, rate limiting, cost guard
- **Infrastructure:** Docker multi-stage, Redis, docker-compose

**Tất cả production patterns đã được áp dụng:**

| Requirement | Implementation |
|-------------|----------------|
| Config từ env | `app/config.py` — 12-factor |
| API key auth | `app/auth.py` — X-API-Key header |
| Rate limiting | `app/rate_limiter.py` — 10 req/min |
| Cost guard | `app/cost_guard.py` — $10/month per user |
| Health check | `GET /health` — liveness probe |
| Readiness check | `GET /ready` — waits for RAG init |
| Graceful shutdown | SIGTERM + uvicorn 30s timeout |
| Stateless | Conversation history in Redis |
| Structured logging | JSON format throughout |
| Multi-stage Docker | python:3.11-slim, non-root user |
| No hardcoded secrets | Tất cả từ env vars |
