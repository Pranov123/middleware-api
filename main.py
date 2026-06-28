from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from collections import defaultdict, deque
import threading
import time
import uuid

app = FastAPI()

EMAIL = "23f3004298@ds.study.iitm.ac.in"
RATE_LIMIT = 15
WINDOW = 10

client_requests: dict = defaultdict(deque)
client_locks_map: dict = {}
global_lock = threading.Lock()


def get_client_lock(client_id: str) -> threading.Lock:
    with global_lock:
        if client_id not in client_locks_map:
            client_locks_map[client_id] = threading.Lock()
        return client_locks_map[client_id]


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

    # ---------------- REQUEST ID ----------------
    inbound_id = request.headers.get("x-request-id")
    request_id = inbound_id if inbound_id else str(uuid.uuid4())
    request.state.request_id = request_id

    origin = request.headers.get("origin", "")

    cors = {}
    if origin:
        cors = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
        }

    # ---------------- PREFLIGHT ----------------
    if request.method == "OPTIONS":
        return JSONResponse(
            status_code=200,
            content={"ok": True},
            headers={
                "X-Request-ID": request_id,
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Max-Age": "86400",
                **cors,
            },
        )

    # ---------------- RATE LIMIT ----------------
    client_id = request.headers.get("x-client-id", "anonymous")

    if not check_rate_limit(client_id):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={
                "Retry-After": str(WINDOW),
                "X-Request-ID": request_id,
                **cors,
            },
        )

    # ---------------- CALL APP ----------------
    response = await call_next(request)

    # 🔥 CRITICAL FIX: ALWAYS SET HEADER HERE
    @app.get("/ping")
    async def ping(request: Request):
        return {
            "email": EMAIL,
            "request_id": request.state.request_id
        }

    for k, v in cors.items():
        response.headers[k] = v

    return response


@app.get("/ping")
async def ping(request: Request, response: Response):
    request_id = request.state.request_id
    # Set header here too — belt AND suspenders
    response.headers["X-Request-ID"] = request_id
    return {
        "email": EMAIL,
        "request_id": request_id,
    }