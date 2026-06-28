from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from collections import defaultdict, deque
import threading
import time
import uuid

app = FastAPI()

EMAIL = "23f3004298@ds.study.iitm.ac.in"

ALLOWED_ORIGINS = [
    "https://app-fqni5r.example.com",
    "https://exam.sanand.workers.dev",  # exam page origin
]

RATE_LIMIT = 15
WINDOW = 10

client_requests: dict = defaultdict(deque)
client_locks: dict = defaultdict(threading.Lock)
global_lock = threading.Lock()


def get_client_lock(client_id: str) -> threading.Lock:
    with global_lock:
        if client_id not in client_locks:
            client_locks[client_id] = threading.Lock()
        return client_locks[client_id]


def check_rate_limit(client_id: str) -> bool:
    now = time.time()
    lock = get_client_lock(client_id)
    with lock:
        dq = client_requests[client_id]
        while dq and now - dq[0] > WINDOW:
            dq.popleft()
        if len(dq) >= RATE_LIMIT:
            return False
        dq.append(now)
        return True


@app.middleware("http")
async def middleware_stack(request: Request, call_next):
    # ── 1. Request-context ──────────────────────────────────────
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id

    origin = request.headers.get("origin", "")

    # ── 2. CORS preflight ───────────────────────────────────────
    if request.method == "OPTIONS":
        if origin in ALLOWED_ORIGINS:
            return JSONResponse(
                status_code=200,
                content="OK",
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Allow-Credentials": "true",
                    "X-Request-ID": request_id,
                },
            )
        return JSONResponse(status_code=403, content={"detail": "CORS origin not allowed"})

    # ── 3. Per-client rate limiting ─────────────────────────────
    client_id = request.headers.get("x-client-id", "anonymous")
    if not check_rate_limit(client_id):
        response = JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={
                "Retry-After": str(WINDOW),
                "X-Request-ID": request_id,
            },
        )
        if origin in ALLOWED_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
        return response

    # ── 4. Process request ──────────────────────────────────────
    response = await call_next(request)

    # ── 5. Attach headers to every response ─────────────────────
    response.headers["X-Request-ID"] = request_id
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"

    return response


@app.get("/ping")
async def ping(request: Request):
    return {
        "email": EMAIL,
        "request_id": request.state.request_id,
    }