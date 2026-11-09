"""Offline test of token usage + real cost per video (usage.py), the budget using it, and the admin cost endpoints.
Run: python test_usage.py"""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS

tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake",
                  DATABASE_URL=f"sqlite:///{tmp}/t.db", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", USD_THB="35")

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import capacity  # noqa: E402
import usage  # noqa: E402
from admin import settings as S  # noqa: E402
from db import Job, Session, User, add_usage, update_job, utcnow  # noqa: E402
from main import app  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


# 1. the three answer shapes (field names as measured on real Gemini answers, 2026-11-09)
usage.start("j1")
text = NS(usage_metadata=NS(prompt_token_count=1000, tool_use_prompt_token_count=None, candidates_token_count=300, thoughts_token_count=100,
                            prompt_tokens_details=[NS(modality="MediaModality.AUDIO", token_count=800), NS(modality="MediaModality.TEXT", token_count=200)]))
usage.record_generate_content(text, "gemini-3.8-flash")
inter = NS(usage=NS(input_tokens_by_modality=[NS(modality="text", tokens=17)], output_tokens_by_modality=[NS(modality="audio", tokens=71)],
                    total_input_tokens=17, total_output_tokens=71))
usage.record_interaction(inter, "gemini-3.8-flash-tts")
usage.record_cloud_tts("cloud/gemini-2.5-flash-tts", "x" * 30, 4.0)
usage.record_claude(NS(model="claude-haiku-5-5", usage=NS(input_tokens=500, output_tokens=200, cache_creation_input_tokens=0, cache_read_input_tokens=0)))
snap = usage.snapshot("j1")
ok(snap["gemini-3.8-flash"] == {"calls": 1, "in": 200, "audio_in": 800, "out": 400, "audio_out": 0, "est": 0}, f"text answer: audio in split, thinking counted as output {snap['gemini-3.8-flash']}")
ok(snap["gemini-3.8-flash-tts"]["audio_out"] == 71 and snap["gemini-3.8-flash-tts"]["in"] == 17, "TTS answer: 17 text in, 71 audio out")
ok(snap["cloud/gemini-2.5-flash-tts"]["audio_out"] == 100 and snap["cloud/gemini-2.5-flash-tts"]["est"] == 1, "Cloud TTS: 4 s -> 100 audio tokens, flagged as estimate")
ok(snap["claude-haiku-5-5"]["in"] == 500 and snap["claude-haiku-5-5"]["out"] == 200, "Claude answer counted")

# 2. job id reaches worker threads
usage.install()
with ThreadPoolExecutor(2) as ex:
    seen = list(ex.map(lambda _: usage.current(), range(3)))
ok(seen == ["j1"] * 3, "worker threads inherit the job id")
usage.start(None)

# 3. the Gemini text hook (a fake original method stands in for the network)
import google.genai.models as gm  # noqa: E402
usage._installed = False
gm.Models.generate_content = lambda self, *a, **k: text
usage.install()
usage.start("j2")
gm.Models.generate_content(None, model="gemini-3.8-flash", contents="x")
ok(usage.snapshot("j2")["gemini-3.8-flash"]["calls"] == 1, "generate_content hook records usage")
usage.start(None)

# 4. prices -> THB (35 THB per USD)
one = usage.cost_thb({"gemini-3.8-flash-tts": {"in": 17, "audio_out": 71}})
usd = (17 * 0.50 + 71 * 9.0) / 1e6
ok(abs(one["thb"] - usd * 35) < 1e-9 and one["complete"], f"3.8 flash TTS: 71 audio tokens = {one['thb']:.4f} THB")
ok(not usage.cost_thb(snap)["complete"] and usage.cost_thb(snap)["unpriced"] == ["claude-haiku-5-5"], "Claude has no default price -> incomplete, named")
ok(usage.cost_thb({"cloud/gemini-2.5-flash-tts": {"in": 10, "audio_out": 100, "est": 1}})["estimated"], "estimated flag carried")

# 5. saved into the job, also for a cancelled job
S.update(budget_thb=100.0, budget_enabled=True, cost_per_minute_thb=1.0, min_free_minutes=30.0)   # (counts what is used from now on)
import time; time.sleep(0.01)
with Session() as s:
    admin = User(email="boss@x.com", password_hash=auth.hash_password("password1"), is_admin=True, plan=None) if False else User(
        email="boss@x.com", password_hash=auth.hash_password("password1"), is_admin=True, daily_minutes=1000, monthly_minutes=100000)
    s.add(admin); s.commit(); uid = admin.id
    for i in range(1, 6):
        s.add(Job(id=f"d{i}", user_id=uid, status="done", params={}, data={}, charged_seconds=600.0, created_at=utcnow()))
    s.add(Job(id="c1", user_id=uid, status="cancelled", params={}, data={}, charged_seconds=0.0, created_at=utcnow()))
    s.add(Job(id="r1", user_id=uid, status="running", params={}, data={}, charged_seconds=600.0, created_at=utcnow()))
    s.commit()
update_job("c1", status="cancelled")
add_usage("c1", {"gemini-3.8-flash-tts": {"calls": 1, "in": 10, "audio_in": 0, "out": 0, "audio_out": 1000, "est": 0}})
with Session() as s:
    ok(s.get(Job, "c1").data["usage"]["gemini-3.8-flash-tts"]["audio_out"] == 1000, "usage saved for a cancelled job (its tokens were paid)")

# 6. budget: real cost replaces the estimate. 5 finished 10-min videos at 2.0 THB real cost each (estimate would be 10 THB each).
per_video_usd = 2.0 / 35
audio_tokens = per_video_usd * 1e6 / 9.0
for i in range(1, 6):
    add_usage(f"d{i}", {"gemini-3.8-flash-tts": {"calls": 10, "in": 0, "audio_in": 0, "out": 0, "audio_out": audio_tokens, "est": 0}})
with Session() as s:
    m = capacity.measured_cost_per_minute(s)
    b = capacity.budget(s)
ok(m is not None and abs(m - 0.2) < 1e-6, f"measured cost per minute = 0.20 THB (5 videos, 2 THB per 10 min): {m}")
# spent = 5 x 2.0 real + cancelled job's real cost + running job at estimate (10 min x 0.2) = 10 + c1 + 2
c1 = usage.cost_thb({"gemini-3.8-flash-tts": {"in": 10, "audio_out": 1000}})["thb"]
ok(abs(b["spent_thb"] - round(10 + c1 + 2.0, 1)) < 0.11 and b["videos_priced_from_tokens"] >= 5, f"budget uses real token cost: spent {b['spent_thb']} THB (estimate would be 60)")
ok(b["cost_per_minute_measured"] == 0.2 and b["available_minutes"] > 400, f"free budget in minutes uses the measured cost: {b['available_minutes']} min")

# 7. admin: costs, prices, audit
tok = auth.make_token(User(id=uid, email="boss@x.com", password_hash="x", is_admin=True)) if False else None
with Session() as s:
    tok = auth.make_token(s.get(User, uid))
c = TestClient(app)
H = {"Authorization": f"Bearer {tok}"}
r = c.get("/api/admin/costs", headers=H).json()
ok(r["usd_thb"] == 35 and r["measured_cost_per_minute"] == 0.2 and any(x["model"] == "gemini-3.8-flash-tts" and x["calls"] >= 50 for x in r["models"]), "/costs: models with usage, measured cost per minute")
ok(len(r["recent"]) >= 1 and r["recent"][0]["complete"], "/costs: recent videos priced")
jobs = c.get("/api/admin/jobs", headers=H).json()["items"]
ok(any(j["id"] == "d1" and abs(j["cost_thb"] - 2.0) < 0.01 for j in jobs), "jobs list shows the real cost of a video")
before = r["total_thb_30d"]
r2 = c.put("/api/admin/settings", headers=H, json={"prices": {"gemini-3.8-flash-tts": {"in": 1.0, "audio_out": 18.0}}, "usd_thb": 36}).json()
ok(r2["prices"]["gemini-3.8-flash-tts"]["audio_out"] == 18.0 and r2["usd_thb"] == 36, "owner edits a price and the rate")
after = c.get("/api/admin/costs", headers=H).json()
ok(after["total_thb_30d"] > before * 1.9, f"history re-priced at once ({before} -> {after['total_thb_30d']})")
ok(c.put("/api/admin/settings", headers=H, json={"prices": {"x": {"in": -1}}}).status_code == 400, "negative price refused")
ok(c.put("/api/admin/settings", headers=H, json={"prices": {"x": {"cost": 1}}}).status_code == 400, "unknown price field refused")
ok("prices" in str(c.get("/api/admin/audit?action=settings.update", headers=H).json()), "price change is in the audit log")
ok(c.get("/api/admin/costs").status_code == 401, "costs need an admin")
print("ALL OK")
