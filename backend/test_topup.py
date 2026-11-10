"""Offline test: pay-as-you-go minutes: packs + price, QR, slip upload, approve / reject, bought minutes used after the allowance,
refund on failure, manual credit, audit. Run: python test_topup.py"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake",
                  DATABASE_URL=f"sqlite:///{tmp}/t.db", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", MAX_VIDEO_MINUTES="600", MAX_ACTIVE_JOBS_PER_USER="50")

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
from db import Job, Session, User, update_job  # noqa: E402

main.jobs_queue.enqueue = lambda job_id: None
main.media_duration = lambda path: 600.0   # every video is 10 minutes
for d in ("data", "up", "out"):
    os.makedirs(f"{tmp}/{d}", exist_ok=True)


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


with Session() as s:
    s.add(User(email="boss", password_hash="x", is_admin=True))
    s.add(User(email="amy", password_hash="x", daily_minutes=15, monthly_minutes=1000))
    s.commit()
    A = {"Authorization": f"Bearer {auth.make_token(s.query(User).filter_by(email='boss').one())}"}
    amy = s.query(User).filter_by(email="amy").one()
    U, uid = {"Authorization": f"Bearer {auth.make_token(amy)}"}, amy.id
c = TestClient(main.app)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 50


def credit():
    with Session() as s:
        return round(s.get(User, uid).credit_seconds / 60, 1)


def video(**kw):
    return c.post("/api/jobs", headers=U, files={"video_file": ("a.mp4", b"x" * 50, "video/mp4")}, data={"voice_type": "Kore", **kw})


# ---- pricing ----
p = c.get("/api/admin/pricing", headers=A).json()
ok(p["price_per_minute"] == 5 and [x["minutes"] for x in p["packs"]] == [30, 60, 100, 200] and p["packs"][0]["price_thb"] == 150, "default 5 THB/min, packs 30/60/100/200 (30 min = 150 THB)")
ok(p["margin_percent"]["premium"] is not None, "margin shown against the cost per minute")
ok(c.put("/api/admin/settings", headers=A, json={"price_per_minute_thb": 4, "topup_packs": [100, 30], "payment_note": "KBank 123"}).json()["price_per_minute_thb"] == 4, "admin changes the price + packs")
t = c.get("/api/topup", headers=U).json()
ok([x["minutes"] for x in t["packs"]] == [30, 100] and t["packs"][1]["price_thb"] == 400 and t["qr_url"] is None and t["payment_note"] == "KBank 123", "user sees the new packs and prices")
c.put("/api/admin/settings", headers=A, json={"price_per_minute_thb": 5, "topup_packs": [30, 60, 100, 200]})

# ---- QR + slip ----
slip = lambda m, data=PNG, name="s.png": c.post("/api/topup/requests", headers=U, data={"minutes": m, "note": "paid"}, files={"slip": (name, data, "image/png")})  # noqa: E731
ok(slip(30).status_code == 503, "no QR yet: top-up not available")
ok(c.post("/api/admin/payment-qr", headers=A, files={"file": ("q.png", b"not an image", "image/png")}).status_code == 400, "QR must be a real picture")
q = c.post("/api/admin/payment-qr", headers=A, files={"file": ("q.png", PNG, "image/png")})
ok(q.status_code == 200 and q.json()["qr_url"], "admin uploads the QR")
url = c.get("/api/topup", headers=U).json()["qr_url"]
ok(c.get(url).status_code == 200, "user can load the QR through the signed link")
ok(c.get(url.split("sig=")[0] + "sig=bad").status_code == 403 and c.get("/api/private/payment_qr_x.png?exp=1&sig=x").status_code == 403, "bad / expired links refused")
ok(slip(7).status_code == 400, "only the listed packs")
ok(slip(30, b"hello").status_code == 400, "a slip must be a picture or PDF (checked by content)")
r = slip(30)
ok(r.status_code == 200 and r.json()["status"] == "pending" and r.json()["amount_thb"] == 150, "slip submitted: pending, 150 THB")
slip(60); slip(100)
ok(slip(200).status_code == 429, "at most 3 waiting requests")

# ---- admin checks the slips ----
lst = c.get("/api/admin/topups?status=pending", headers=A).json()
ok(lst["total"] == 3 and lst["items"][0]["email"] == "amy" and c.get(lst["items"][0]["slip_url"]).status_code == 200, "admin sees pending requests and can open the slip")
ok(c.get("/api/admin/overview", headers=A).json()["topups_pending"] == 3, "overview counts pending top-ups")
ids = {i["minutes"]: i["id"] for i in lst["items"]}
ok(c.post(f"/api/admin/topups/{ids[30]}/approve", headers=U).status_code == 403, "a normal user cannot approve")
ok(c.post(f"/api/admin/topups/{ids[30]}/approve", headers=A).json()["credit_minutes"] == 30 and credit() == 30, "approve adds 30 minutes")
ok(c.post(f"/api/admin/topups/{ids[30]}/approve", headers=A).status_code == 409 and credit() == 30, "approving twice adds nothing more")
ok(c.post(f"/api/admin/topups/{ids[60]}/reject", headers=A, json={"reason": "amount does not match"}).json()["status"] == "rejected" and credit() == 30, "reject adds nothing")
mine = c.get("/api/topup", headers=U).json()
ok(any(x["status"] == "rejected" and x["admin_note"] == "amount does not match" for x in mine["requests"]) and mine["credit_minutes"] == 30, "user sees the result and the reason")

# ---- bought minutes are used AFTER the allowance (daily 15 min) ----
r1 = video()                      # 10 min: inside the 15-minute allowance
ok(r1.status_code == 200 and credit() == 30, "first video uses the allowance only")
r2 = video()                      # 10 more: 5 left in the allowance, 5 minutes from the bought ones
with Session() as s:
    j2 = s.get(Job, r2.json()["job_id"])
    ok(r2.status_code == 200 and round(j2.charged_seconds / 60, 1) == 5.0 and round(j2.credit_seconds / 60, 1) == 5.0 and credit() == 25, "second video: 5 min allowance + 5 min bought")
me = c.get("/api/auth/me", headers=U).json()
ok(me["credit_seconds"] == 25 * 60 and me["allowance_remaining_seconds"] == 0 and me["remaining_seconds"] == 25 * 60, "/me shows bought minutes and what can still be made")
update_job(r2.json()["job_id"], status="error", stage="Failed")
ok(credit() == 30, "a failed video gives the bought minutes back")
update_job(r2.json()["job_id"], status="error", stage="Failed")
ok(credit() == 30, "...only once")
for _ in range(3):
    video()
r5 = video()
ok(r5.status_code == 402 and "Top up" in r5.json()["detail"], f"out of bought minutes: {r5.json()['detail'][:60]}...")

# ---- manual credit ----
ok(c.post(f"/api/admin/users/{uid}/credit", headers=A, json={"minutes": 100, "note": "cash"}).json()["credit_minutes"] > 100, "admin adds minutes by hand")
ok(c.post(f"/api/admin/users/{uid}/credit", headers=A, json={"minutes": -100000}).json()["credit_minutes"] == 0, "taking back never goes below 0")
ok(c.post(f"/api/admin/users/{uid}/credit", headers=A, json={"minutes": 0}).status_code == 400, "0 minutes refused")
row = next(u for u in c.get("/api/admin/users", headers=A).json()["items"] if u["id"] == uid)
ok("credit_minutes" in row, "Users table carries the balance")
logs = c.get("/api/admin/audit?per_page=100", headers=A).json()["items"]
acts = {l["action"] for l in logs}
ok({"topup.approve", "topup.reject", "credit.adjust"} <= acts, "approvals, rejections and manual credit are in the audit log")
ok(c.delete("/api/admin/payment-qr", headers=A).json()["qr_url"] is None, "admin can remove the QR")
print("ALL OK")
