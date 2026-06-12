# Deployment Information — DrugLaw RAG Agent

## Public URL

> **TODO:** Điền URL sau khi deploy xong.

```
https://your-agent.railway.app
```

## Platform

Railway *(hoặc Render)*

## Deploy Steps (Railway)

```bash
cd 06-lab-complete

npm i -g @railway/cli
railway login
railway init

# Set secrets
railway variables set GROQ_API_KEY=gsk_your_key_here
railway variables set AGENT_API_KEY=your-secret-key
railway variables set ENVIRONMENT=production

railway up
railway domain
```

## Environment Variables

| Variable | Value |
|----------|-------|
| `GROQ_API_KEY` | *(secret — lấy từ console.groq.com)* |
| `AGENT_API_KEY` | *(secret — tự đặt)* |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `MONTHLY_BUDGET_USD` | `10.0` |

## Test Commands

### Health Check
```bash
curl https://your-agent.railway.app/health
# Expected: {"status":"ok","version":"2.0.0",...}
```

### Auth Required (no key → 401)
```bash
curl -X POST https://your-agent.railway.app/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# Expected: 401 Unauthorized
```

### Câu hỏi về luật (with key → 200)
```bash
curl -X POST https://your-agent.railway.app/ask \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hình phạt tàng trữ heroin theo Điều 249 là bao nhiêu năm tù?", "user_id": "test"}'
# Expected: {"answer":"...với citation nguồn...","sources":[...],...}
```

### Rate Limiting (→ 429 sau 10 requests)
```bash
for i in $(seq 1 15); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST https://your-agent.railway.app/ask \
    -H "X-API-Key: your-secret-key" \
    -H "Content-Type: application/json" \
    -d '{"question": "test", "user_id": "test"}'
done
# Sau request 10: 429 Too Many Requests
```

## Screenshots

- `screenshots/dashboard.png` — Railway deployment dashboard
- `screenshots/running.png` — Service logs đang chạy
- `screenshots/test.png` — Kết quả curl test với câu hỏi về luật
