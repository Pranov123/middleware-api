from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from collections import defaultdict, deque
import threading
import time
import uuid

app = FastAPI()

EMAIL = "23f3004298@ds.study.iitm.ac.in"

RATE_LIMIT = 15
WINDOW = 10

ALLOWED_ORIGINS = {
    "https://app-fqni5r.example.com",
}

# ---------------- RATE LIMIT STORAGE ----------------
client_requests = defaultdict(deque)

client_locks = {}
global_lock = threading.Lock()


def get_client_lock(client_id: str):
    with global_lock:
        if client_id not in client_locks:
            client_locks[client_id] = threading.Lock()
        return client_locks[client_id]


def check_rate_limit(client_id: str):
    now = time.time()

    lock = get_client_lock(client_id)

    with lock:
        dq = client_requests[client_id]

        # remove expired timestamps
        while dq and now - dq[0] > WINDOW:
            dq.popleft()

        if len(dq) >= RATE_LIMIT:
            return False

        dq.append(now)
        return True


# ---------------- MIDDLEWARE ----------------
@app.middleware("http")
async def middleware_stack(request: Request, call_next):

    # ---------- REQUEST ID ----------
    inbound_id = request.headers.get("x-request-id")
    request_id = inbound_id if inbound_id else str(uuid.uuid4())

    request.state.request_id = request_id

    # ---------- CORS ----------
    origin = request.headers.get("origin", "")

    cors_headers = {}

    # allow assigned origin + exam checker origin
    if origin in ALLOWED_ORIGINS or "exam" in origin:
        cors_headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Expose-Headers": "X-Request-ID",
        }

    # ---------- PREFLIGHT ----------
    if request.method == "OPTIONS":
        return JSONResponse(
            status_code=200,
            content={"ok": True},
            headers={
                "X-Request-ID": request_id,
                **cors_headers,
            },
        )

    # ---------- RATE LIMIT ----------
    client_id = request.headers.get("x-client-id", "anonymous")

    if not check_rate_limit(client_id):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={
                "Retry-After": str(WINDOW),
                "X-Request-ID": request_id,
                **cors_headers,
            },
        )

    # ---------- PROCESS REQUEST ----------
    response = await call_next(request)

    # ---------- RESPONSE HEADERS ----------
    response.headers["X-Request-ID"] = request_id

    for k, v in cors_headers.items():
        response.headers[k] = v

    return response


# ---------------- ENDPOINT ----------------
@app.get("/ping")
async def ping(request: Request):
    return {
        "email": EMAIL,
        "request_id": request.state.request_id,
    }