# Day 12 Lab — Mission Answers

**Student Name:** Le Quoc Anh  
**Student ID:** 2A202600824  
**Date:** 2026-06-12

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found in `01-localhost-vs-production/develop/app.py`

1. **API key hardcoded** — `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` — lộ secret ngay khi push lên GitHub.
2. **Database URL hardcoded** — `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"` — chứa cả username và password.
3. **Debug mode bật cứng** — `DEBUG = True` và `reload=True` trong uvicorn — không bao giờ dùng trong production.
4. **Dùng `print()` thay vì logging** — không có log level, không thể filter, không thể gửi vào log aggregator.
5. **Log ra secret** — `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` — key bị expose trong stdout/log.
6. **Không có health check endpoint** — platform (Railway, Kubernetes) không biết khi nào restart container.
7. **Port cứng 8000** — không đọc từ `PORT` env var, Railway/Render inject port qua env.
8. **Binding trên `localhost`** — container chỉ nghe nội bộ, không nhận traffic từ bên ngoài; phải dùng `0.0.0.0`.

### Exercise 1.3: Comparison table — Develop vs Production

| Feature | Develop (`develop/app.py`) | Production (`production/app.py`) | Tại sao quan trọng? |
|---------|---------------------------|----------------------------------|---------------------|
| Config | Hardcode trong code | Đọc từ env vars qua `Settings` dataclass | Secrets không lộ, dễ thay đổi theo môi trường |
| Health check | Không có | `/health` (liveness) + `/ready` (readiness) | Platform tự động restart khi agent crash |
| Logging | `print()` in ra màn hình | JSON structured logging với `logging` module | Dễ parse bởi Datadog/Loki, có log level |
| Host binding | `localhost` — chỉ local | `0.0.0.0` — nhận traffic từ bên ngoài container | Container phải nghe trên tất cả interfaces |
| Port | Hardcode `8000` | Đọc từ `PORT` env var | Railway/Render inject port động |
| Debug/reload | Luôn bật | Chỉ bật khi `DEBUG=true` | reload làm chậm và gây lỗi trong production |
| Graceful shutdown | Không có | SIGTERM handler + lifespan context | Cho request đang xử lý hoàn thành trước khi tắt |
| CORS | Không có | Middleware chỉ cho phép `allowed_origins` | Ngăn cross-origin request không hợp lệ |

---

## Part 2: Docker

### Exercise 2.1: Câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` — full Python distribution (~1 GB).
2. **Working directory:** `/app`.
3. **Tại sao COPY requirements.txt trước?** Docker build theo từng layer và cache từng bước. `requirements.txt` ít thay đổi hơn code nên cache layer install dependencies vẫn hợp lệ cho các lần build sau — chỉ rebuild khi requirements thực sự thay đổi, tiết kiệm thời gian đáng kể.
4. **CMD vs ENTRYPOINT:**  
   - `CMD` là default command, có thể bị override khi chạy `docker run image <custom-cmd>`.  
   - `ENTRYPOINT` là fixed command, không thể override — chỉ thêm arguments. Dùng `ENTRYPOINT` cho binary chính, `CMD` cho default arguments.

### Exercise 2.3: Multi-stage build — `02-docker/production/Dockerfile`

- **Stage 1 (builder):** Cài `gcc`, `libpq-dev`, rồi `pip install --user -r requirements.txt`. Stage này cần build tools để compile một số native packages.
- **Stage 2 (runtime):** Bắt đầu từ `python:3.11-slim` sạch, chỉ copy `/root/.local` (packages đã compile) từ builder sang. Không copy gcc, apt cache, hay build tools → image nhỏ hơn nhiều.
- **Tại sao image nhỏ hơn?** Slim image không có nhiều system packages. Build tools (gcc ~200 MB) không được copy vào runtime stage. Kết quả: develop image ~1 GB, production image ~200-250 MB.

### Exercise 2.4: Docker Compose stack

Services được start từ `02-docker/production/docker-compose.yml`:
- **nginx** — reverse proxy / load balancer, expose port 80 ra ngoài
- **agent** — FastAPI app, có thể scale nhiều instance
- **redis** — lưu session/state để stateless design

Communication: Client → Nginx (port 80) → Agent (port 8000, internal) → Redis (port 6379, internal). Nginx và Agent dùng Docker internal network, không expose ra ngoài.

---

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment

- **Platform:** Railway
- **URL:** *(điền sau khi deploy — xem `DEPLOYMENT.md`)*
- **Cách deploy:**
  ```bash
  npm i -g @railway/cli
  railway login
  railway init
  railway variables set PORT=8000
  railway variables set AGENT_API_KEY=my-secret-key
  railway up
  railway domain
  ```

### Exercise 3.2: So sánh `render.yaml` vs `railway.toml`

| | `railway.toml` | `render.yaml` |
|--|----------------|---------------|
| Format | TOML | YAML |
| Build command | `[build] builder = "DOCKERFILE"` | `services[].env: docker` |
| Health check | Tự detect từ Dockerfile | Khai báo rõ `healthCheckPath` |
| Scaling | Dashboard hoặc `railway scale` | `numInstances` trong yaml |
| Environment vars | `railway variables set` hoặc dashboard | Dashboard (secrets) + yaml (non-secret) |

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)

- **API key được check ở đâu?** Trong `verify_api_key()` dependency — inject vào endpoint qua `Depends(verify_api_key)`. Kiểm tra header `X-API-Key` với giá trị trong env var `AGENT_API_KEY`.
- **Điều gì xảy ra nếu sai key?**  
  - Không có key → HTTP 401 `Missing API key`  
  - Sai key → HTTP 403 `Invalid API key`
- **Làm sao rotate key?** Đổi giá trị `AGENT_API_KEY` trong environment variables, restart service. Không cần thay đổi code.

### Exercise 4.2: JWT flow (`04-api-gateway/production/auth.py`)

1. Client gửi `POST /auth/token` với `{"username": "student", "password": "demo123"}`.
2. Server verify credentials, tạo JWT có `sub`, `role`, `exp` (60 phút), ký bằng `JWT_SECRET`.
3. Client gửi mọi request với header `Authorization: Bearer <token>`.
4. Server decode JWT, verify signature và expiry, extract `username` + `role`.
5. Token hết hạn → client phải đăng nhập lại.
6. **Ưu điểm so với API key:** Stateless (không cần check DB), có expiry tự động, mang thêm thông tin role.

### Exercise 4.3: Rate Limiting (`04-api-gateway/production/rate_limiter.py`)

- **Algorithm:** Sliding Window Counter — mỗi user có một `deque` timestamps; loại bỏ timestamps cũ hơn 60 giây trước khi đếm.
- **Limit:** 10 req/phút cho user, 100 req/phút cho admin (2 instance riêng biệt).
- **Bypass cho admin:** `rate_limiter_admin` được dùng khi `role == "admin"` — limit cao hơn 10x.
- **Response khi hit limit:** HTTP 429 với header `Retry-After` và `X-RateLimit-*`.

### Exercise 4.4: Cost Guard Implementation

Đã implement trong `06-lab-complete/app/cost_guard.py`:

```python
def check_budget() -> None:
    _reset_if_new_day()
    if _daily_cost >= settings.daily_budget_usd:
        raise HTTPException(503, "Daily budget exhausted. Try again tomorrow.")

def record_usage(input_tokens: int, output_tokens: int) -> None:
    global _daily_cost
    _reset_if_new_day()
    _daily_cost += (input_tokens / 1000) * 0.00015
    _daily_cost += (output_tokens / 1000) * 0.0006
```

**Approach:** Track tổng chi phí theo ngày trong memory. Reset lúc đầu ngày mới. `check_budget()` gọi trước khi gọi LLM, `record_usage()` gọi sau khi nhận response. Raise HTTP 503 thay vì 402 để client biết thử lại sau.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks

```python
@app.get("/health")
def health():
    return {"status": "ok"}  # Liveness: process còn chạy

@app.get("/ready")
def ready():
    if not _is_ready:
        raise HTTPException(503, "Not ready")
    return {"ready": True}   # Readiness: đã init xong, sẵn sàng nhận traffic
```

**Sự khác biệt:**
- `/health` (liveness): "Container còn sống không?" — platform restart nếu fail.
- `/ready` (readiness): "Sẵn sàng nhận request chưa?" — load balancer stop routing nếu fail (trong khi startup, overload, v.v.).

### Exercise 5.2: Graceful Shutdown

```python
def handle_sigterm(*args):
    logger.info("Received SIGTERM — initiating graceful shutdown")
    # uvicorn với timeout_graceful_shutdown=30 tự xử lý in-flight requests

signal.signal(signal.SIGTERM, handle_sigterm)
```

**Test:** Khi `kill -TERM $PID`, container không dừng ngay mà chờ request đang xử lý hoàn thành (trong 30s), sau đó mới exit 0. Khác với `kill -9` (SIGKILL) không thể catch.

### Exercise 5.3: Stateless Design

**Anti-pattern (in-memory):**
```python
conversation_history = {}  # Mỗi instance có memory riêng
```
Khi scale ra 3 instances, request A vào instance 1, request B vào instance 2 → instance 2 không thấy history của instance 1.

**Correct (Redis):**
```python
@app.post("/ask")
def ask(user_id: str, question: str):
    history = r.lrange(f"history:{user_id}", 0, -1)
```
Tất cả instances đọc/ghi cùng Redis → stateless, có thể scale tùy ý.

### Exercise 5.4: Load Balancing

```bash
docker compose up --scale agent=3
```

Kết quả: 3 agent container được start, Nginx phân tán request round-robin. Nếu 1 instance die, Nginx detect qua health check và ngừng route vào instance đó — zero downtime.

Từ `docker compose logs agent`, thấy request được phân tán đều cho các container khác nhau (container ID khác nhau xử lý).

### Exercise 5.5: Stateless Test

`test_stateless.py` kiểm tra:
1. Tạo conversation trên instance A
2. Kill instance A
3. Tiếp tục conversation → vẫn nhận đúng history từ Redis

**Kết quả:** Conversation không mất vì state lưu trong Redis, không trong memory của instance bị kill.

---

## Part 6: Final Project

Xem source code đầy đủ trong thư mục `06-lab-complete/`.

**Architecture đã implement:**
- FastAPI app với tất cả features từ Part 1-5
- Multi-stage Dockerfile (< 500 MB)
- Config từ environment variables (12-factor)
- API Key authentication (`app/auth.py`)
- Rate limiting 10 req/min (`app/rate_limiter.py`)
- Cost guard $10/tháng per user (`app/cost_guard.py`)
- `/health` + `/ready` endpoints
- Graceful shutdown (SIGTERM handler + uvicorn `timeout_graceful_shutdown=30`)
- Structured JSON logging
- Docker Compose với Redis
- Railway + Render deployment config
