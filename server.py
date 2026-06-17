import asyncio
import csv
import io
import json
import queue as stdlib_queue
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from core.auth import AuthManager, User
from core.database import Database
from core.network_scanner import NetworkScanner
from core.permissions_manager import ACCESS_LEVELS, PermissionsManager
from core.settings_manager import SettingsManager

SECRET = "it-help-jwt-secret-change-in-production"
ALGORITHM = "HS256"
TOKEN_HOURS = 8

app = FastAPI(title="IT Help", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

db = Database()
db.initialize()
auth_mgr = AuthManager(db)

security = HTTPBearer(auto_error=False)
STATIC = ROOT / "static"

# ── Token helpers ────────────────────────────────────────────────────────
def _make_token(data: dict) -> str:
    payload = {**data, "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)}
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)

def _decode(token: str) -> dict:
    return jwt.decode(token, SECRET, algorithms=[ALGORITHM])

def _user_from_payload(p: dict) -> User:
    return User(id=p["id"], username=p["username"], email=p.get("email", ""), role=p["role"])

def current_user(creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    if not creds:
        raise HTTPException(401, "Not authenticated")
    try:
        return _decode(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")

def sse_user(request: Request) -> dict:
    token = request.query_params.get("token")
    if not token:
        raise HTTPException(401, "Token required")
    try:
        return _decode(token)
    except Exception:
        raise HTTPException(401, "Invalid token")

# ── SSE streaming ────────────────────────────────────────────────────────
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}

def _thread_queue(fn, *args, **kwargs) -> stdlib_queue.Queue:
    q: stdlib_queue.Queue = stdlib_queue.Queue()
    def run():
        try:
            result = fn(*args, progress_cb=q.put, **kwargs)
            q.put(("__done__", result))
        except Exception as exc:
            q.put(("__done__", (False, str(exc))))
    threading.Thread(target=run, daemon=True).start()
    return q

async def _stream(q: stdlib_queue.Queue):
    loop = asyncio.get_event_loop()
    while True:
        item = await loop.run_in_executor(None, q.get)
        if isinstance(item, tuple) and item[0] == "__done__":
            result = item[1]
            if isinstance(result, list):
                yield f"data: {json.dumps({'done': True, 'ok': True, 'count': len(result)})}\n\n"
            elif isinstance(result, tuple):
                ok, msg = result
                yield f"data: {json.dumps({'done': True, 'ok': ok, 'msg': msg})}\n\n"
            else:
                yield f"data: {json.dumps({'done': True, 'ok': True, 'msg': str(result)})}\n\n"
            return
        yield f"data: {json.dumps({'line': str(item)})}\n\n"

# ── Pydantic models ───────────────────────────────────────────────────────
class LoginBody(BaseModel):
    username: str
    password: str

class PermBody(BaseModel):
    target_name: str
    resource_path: str
    access_level: str

class AclBody(BaseModel):
    resource_path: str

class UserBody(BaseModel):
    username: str
    email: str = ""
    role: str
    password: str

# ── Auth ──────────────────────────────────────────────────────────────────
@app.post("/api/auth/login")
async def login(body: LoginBody):
    user = auth_mgr.login(body.username, body.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    if user.role == "Restricted":
        raise HTTPException(403, "Access denied")
    db.log_action(user.username, "login", {"role": user.role})
    token = _make_token({"id": user.id, "username": user.username,
                          "role": user.role, "email": user.email})
    return {"token": token, "user": {"id": user.id, "username": user.username, "role": user.role}}

@app.get("/api/me")
async def me(p=Depends(current_user)):
    return p

# ── Profiles ──────────────────────────────────────────────────────────────
@app.get("/api/profiles")
async def list_profiles(p=Depends(current_user)):
    return [{"name": r["name"], "description": r["description"], "modified_at": r["modified_at"]}
            for r in db.list_profiles()]

@app.get("/api/profiles/{name}/preview")
async def preview_profile(name: str, p=Depends(current_user)):
    mgr = SettingsManager(db, _user_from_payload(p))
    return {"lines": mgr.get_preview(name)}

@app.get("/api/profiles/{name}/apply")
async def apply_profile(name: str, request: Request, p=Depends(sse_user)):
    user = _user_from_payload(p)
    if not user.can("settings"):
        raise HTTPException(403, "Insufficient permissions")
    mgr = SettingsManager(db, user)
    return StreamingResponse(_stream(_thread_queue(mgr.apply_profile, name)),
                             media_type="text/event-stream", headers=SSE_HEADERS)

@app.get("/api/rollbacks")
async def list_rollbacks(p=Depends(current_user)):
    mgr = SettingsManager(db, _user_from_payload(p))
    return {"rollbacks": mgr.list_rollbacks()}

@app.get("/api/rollbacks/restore")
async def restore_rollback(filename: str, request: Request, p=Depends(sse_user)):
    user = _user_from_payload(p)
    if not user.can("settings"):
        raise HTTPException(403, "Insufficient permissions")
    mgr = SettingsManager(db, user)
    return StreamingResponse(_stream(_thread_queue(mgr.rollback, filename)),
                             media_type="text/event-stream", headers=SSE_HEADERS)

# ── Devices ───────────────────────────────────────────────────────────────
@app.get("/api/devices")
async def list_devices(status: str = None, search: str = None, p=Depends(current_user)):
    rows = [dict(r) for r in db.list_devices()]
    if status and status != "all":
        rows = [d for d in rows if (d.get("status") or "").lower() == status.lower()]
    if search:
        s = search.lower()
        rows = [d for d in rows if s in (d.get("hostname") or "").lower()
                or s in (d.get("ip_address") or "").lower()]
    return rows

@app.get("/api/scan")
async def scan_network(request: Request, p=Depends(sse_user)):
    user = _user_from_payload(p)
    scanner = NetworkScanner(db, user)
    q: stdlib_queue.Queue = stdlib_queue.Queue()
    def run():
        try:
            devices = scanner.scan_local(progress_cb=q.put)
            q.put(("__done__", devices))
        except Exception as exc:
            q.put(("__done__", (False, str(exc))))
    threading.Thread(target=run, daemon=True).start()
    return StreamingResponse(_stream(q), media_type="text/event-stream", headers=SSE_HEADERS)

@app.delete("/api/devices/{device_id}")
async def delete_device(device_id: int, p=Depends(current_user)):
    if p["role"] not in ("Admin", "IT_Staff"):
        raise HTTPException(403, "Insufficient permissions")
    db.delete_device(device_id)
    return {"ok": True}

@app.get("/api/devices/export.csv")
async def export_csv(p=Depends(current_user)):
    rows = db.list_devices()
    cols = ["hostname","ip_address","os_version","cpu_model","cores","ram_gb",
            "disk_gb_free","disk_pct_used","cpu_pct","mem_pct","uptime_hours","status","last_seen"]
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(dict(r))
    return Response(content=out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=inventory.csv"})

# ── Permissions ───────────────────────────────────────────────────────────
@app.get("/api/permissions")
async def list_perms(p=Depends(current_user)):
    return [dict(r) for r in db.list_permissions()]

@app.get("/api/permissions/apply")
async def apply_perm(target_name: str, resource_path: str, access_level: str,
                     request: Request, p=Depends(sse_user)):
    user = _user_from_payload(p)
    if not user.can("permissions"):
        raise HTTPException(403, "Admin only")
    mgr = PermissionsManager(db, user)
    return StreamingResponse(
        _stream(_thread_queue(mgr.apply_permission, target_name, resource_path, access_level)),
        media_type="text/event-stream", headers=SSE_HEADERS)

@app.delete("/api/permissions/{perm_id}")
async def revoke_perm(perm_id: int, p=Depends(current_user)):
    if p["role"] != "Admin":
        raise HTTPException(403, "Admin only")
    user = _user_from_payload(p)
    ok, msg = PermissionsManager(db, user).revoke_permission(perm_id)
    if not ok:
        raise HTTPException(404, msg)
    return {"ok": True}

@app.post("/api/acl/query")
async def query_acl(body: AclBody, p=Depends(current_user)):
    user = _user_from_payload(p)
    return {"lines": PermissionsManager(db, user).query_acl(body.resource_path)}

# ── Users ─────────────────────────────────────────────────────────────────
@app.get("/api/users")
async def list_users(p=Depends(current_user)):
    return [{"id": r["id"], "username": r["username"], "email": r["email"] or "",
             "role": r["role"], "created_at": r["created_at"]}
            for r in db.list_users()]

@app.post("/api/users")
async def create_user(body: UserBody, p=Depends(current_user)):
    if p["role"] != "Admin":
        raise HTTPException(403, "Admin only")
    try:
        auth_mgr.create_user(body.username, body.email, body.role, body.password)
        db.log_action(p["username"], "create_user", {"username": body.username, "role": body.role})
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(400, str(exc))

@app.delete("/api/users/{user_id}")
async def delete_user(user_id: int, p=Depends(current_user)):
    if p["role"] != "Admin":
        raise HTTPException(403, "Admin only")
    if user_id == p["id"]:
        raise HTTPException(400, "Cannot delete own account")
    db.delete_user(user_id)
    db.log_action(p["username"], "delete_user", {"user_id": user_id})
    return {"ok": True}

# ── Audit logs ────────────────────────────────────────────────────────────
@app.get("/api/logs")
async def get_logs(limit: int = 300, p=Depends(current_user)):
    if p["role"] not in ("Admin", "IT_Staff"):
        raise HTTPException(403, "Insufficient permissions")
    return [dict(r) for r in db.get_logs(limit)]

# ── Static + SPA ──────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    dummy = User(id=0, username="system", email="", role="Admin")
    SettingsManager(db, dummy).load_profiles_from_disk()

app.mount("/assets", StaticFiles(directory=str(STATIC / "assets")), name="assets")

@app.get("/manifest.json")
async def manifest():
    return FileResponse(str(STATIC / "manifest.json"))

@app.get("/sw.js")
async def service_worker():
    return FileResponse(str(STATIC / "sw.js"), media_type="application/javascript")

@app.get("/{full_path:path}")
async def spa(full_path: str):
    return FileResponse(str(STATIC / "index.html"))


if __name__ == "__main__":
    import uvicorn
    import socket
    host = "0.0.0.0"
    port = 8080
    local_ip = socket.gethostbyname(socket.gethostname())
    print(f"\n  IT Help running at:")
    print(f"  Local:   http://localhost:{port}")
    print(f"  Network: http://{local_ip}:{port}")
    print(f"\n  Open in any browser on this network to use.\n")
    uvicorn.run("server:app", host=host, port=port, reload=False)
