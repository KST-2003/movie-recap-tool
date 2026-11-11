"""Offline check of superadmin / admin / user roles (python test_roles.py)."""
import os, tempfile
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=tmp, UPLOAD_DIR=tmp, OUTPUT_DIR=tmp, DATABASE_URL=f"sqlite:///{tmp}/t.db", GLOBAL_DAILY_MINUTES="0", ALLOW_SIGNUP="true", GCP_PROJECT_ID="")
from fastapi.testclient import TestClient
import main
from db import Session, User
import auth

def ok(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: raise SystemExit(1)

c = TestClient(main.app)
def mk(name, **kw):
    with Session() as s:
        s.add(User(email=name, password_hash=auth.hash_password("password123"), **kw)); s.commit()
def login(name):
    r = c.post("/api/auth/login", json={"email": name, "password": "password123", "device_id": "d-" + name + "-xxxxxxxx"})
    return {"Authorization": "Bearer " + r.json()["token"]}, r.json()
mk("boss", is_admin=True, is_superadmin=True); mk("helper", is_admin=True); mk("alice")
S, sj = login("boss"); A, aj = login("helper"); U, uj = login("alice")
ok(sj["role"] == "superadmin" and aj["role"] == "admin" and uj["role"] == "user", "roles in login")
for path in ("/settings", "/pricing", "/costs"):
    ok(c.get("/api/admin" + path, headers=S).status_code == 200, f"superadmin sees {path}")
    ok(c.get("/api/admin" + path, headers=A).status_code == 403, f"admin refused {path}")
ok(c.put("/api/admin/settings", headers=A, json={"maintenance": True}).status_code == 403, "admin cannot change settings")
ok(c.delete("/api/admin/payment-qr", headers=A).status_code == 403, "admin cannot touch QR")
for path in ("/overview", "/users", "/jobs", "/tts", "/audit", "/topups"):
    ok(c.get("/api/admin" + path, headers=A).status_code == 200, f"admin sees {path}")
ok(c.get("/api/admin/overview", headers=U).status_code == 403, "user refused")
ok(c.post("/api/admin/users", headers=A, json={"username": "bob1", "role": "admin"}).status_code == 403, "admin cannot create admin")
ok(c.post("/api/admin/users", headers=A, json={"username": "bob2", "role": "user"}).status_code == 200, "admin creates user")
r = c.post("/api/admin/users", headers=S, json={"username": "carol", "role": "admin"})
ok(r.status_code == 200 and r.json()["role"] == "admin", "superadmin creates admin")
ok(c.post("/api/admin/users", headers=S, json={"username": "dave1", "role": "superadmin"}).status_code == 400, "superadmin cannot be made in API")
ids = {u["email"]: u["id"] for u in c.get("/api/admin/users?per_page=100", headers=S).json()["items"]}
ok(c.patch(f"/api/admin/users/{ids['alice']}", headers=A, json={"role": "admin"}).status_code == 403, "admin cannot promote")
ok(c.post(f"/api/admin/users/{ids['carol']}/reset-password", headers=A).status_code == 200, "admin can reset another admin's password")
ok(c.delete(f"/api/admin/users/{ids['carol']}/devices", headers=A).status_code == 200, "admin can remove an admin's devices")
ok(c.patch(f"/api/admin/users/{ids['carol']}", headers=A, json={"role": "user"}).status_code == 403, "admin cannot change an admin's role")
ok(c.patch(f"/api/admin/users/{ids['boss']}", headers=A, json={"status": "banned"}).status_code == 403, "admin cannot ban the owner")
ok(c.delete(f"/api/admin/users/{ids['boss']}/devices", headers=A).status_code == 403, "admin cannot remove the owner's devices")
ok(c.post(f"/api/admin/users/{ids['boss']}/reset-password", headers=A).status_code == 403, "admin cannot reset owner password")
ok(c.patch(f"/api/admin/users/{ids['alice']}", headers=A, json={"daily_minutes": 50}).status_code == 200, "admin edits a normal user")
ok(c.patch(f"/api/admin/users/{ids['alice']}", headers=S, json={"role": "admin"}).status_code == 200, "superadmin promotes")
ok(c.patch(f"/api/admin/users/{ids['boss']}", headers=S, json={"role": "user"}).status_code == 400, "owner cannot demote self")
print("all good")
