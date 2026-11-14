"""Offline test of admin/google_quota.py + the 429 limit learning. Google is replaced by canned answers shaped like the
documented Service Usage / Cloud Monitoring responses. Run: python test_google_quota.py"""
import json
import os
import tempfile

tmp = tempfile.mkdtemp()
key = f"{tmp}/sa.json"
open(key, "w").write("{}")
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake",
                  DATABASE_URL=f"sqlite:///{tmp}/t.db", GCP_PROJECT_ID="my-proj", GCP_SERVICE_ACCOUNT_FILE=key)

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import gemini_tts  # noqa: E402
from admin import google_quota as gq  # noqa: E402
from db import Session, User  # noqa: E402
from main import app  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


# ---- learning the real limit from Google's 429 text ----
M = "gemini-3.8-flash-tts"
gemini_tts.learn_limit("429 RESOURCE_EXHAUSTED. Quota exceeded for metric: generativelanguage.googleapis.com/generate_requests_per_model_per_day, limit: 100, model: " + M, M)
gemini_tts.learn_limit("429 You exceeded your current quota. limit: 10 requests per minute on Tier 1", M)
gemini_tts.learn_limit("503 unavailable, no limit mentioned", M)
gemini_tts.learn_limit("limit: 7 something else", "other-model")   # no day/minute word -> ignored
seen = gemini_tts.limits_seen()
ok(seen[M]["per_day"] == 100 and seen[M]["per_minute"] == 10 and seen[M]["metric"].endswith("per_model_per_day"), "429 text -> real day + minute limit and metric learned")
ok("other-model" not in seen, "unclear 429 text is ignored")

# ---- canned Google answers ----
LIMITS = {"metrics": [
    {"metric": "generativelanguage.googleapis.com/generate_requests_per_model_per_day", "displayName": "Generate requests per model per day",
     "consumerQuotaLimits": [{"name": "projects/1/services/x/consumerQuotaMetrics/m/limits/%2Fd%2Fproject%2Fmodel", "unit": "1/d/{project}/{model}",
                              "quotaBuckets": [{"effectiveLimit": "10000", "dimensions": {}},
                                               {"effectiveLimit": "250", "dimensions": {"model": M}},
                                               {"effectiveLimit": "50", "dimensions": {"model": "gemini-2.5-pro-preview-tts"}}]}]},
    {"metric": "generativelanguage.googleapis.com/generate_requests_per_model_per_minute", "displayName": "Generate requests per model per minute",
     "consumerQuotaLimits": [{"name": "projects/1/services/x/consumerQuotaMetrics/m/limits/%2Fmin%2Fproject%2Fmodel", "unit": "1/min/{project}/{model}",
                              "quotaBuckets": [{"effectiveLimit": "30", "dimensions": {"model": M}}]}]},
    {"metric": "generativelanguage.googleapis.com/generate_input_tokens_per_model_per_minute", "displayName": "Input tokens per minute",
     "consumerQuotaLimits": [{"name": "limits/%2Fmin%2Fproject%2Fmodel", "unit": "1/min/{project}/{model}", "quotaBuckets": [{"effectiveLimit": "1000000", "dimensions": {"model": M}}]}]}]}
USAGE = {"timeSeries": [
    {"resource": {"labels": {"service": gq.SERVICE, "project_id": "my-proj"}},
     "metric": {"labels": {"quota_metric": "generativelanguage.googleapis.com/generate_requests_per_model_per_day", "limit_name": "GenerateRequestsPerDayPerProjectPerModel", "model": M}},
     "points": [{"value": {"int64Value": "17"}}, {"value": {"int64Value": "5"}}]},
    {"resource": {"labels": {"service": gq.SERVICE}},
     "metric": {"labels": {"quota_metric": "generativelanguage.googleapis.com/generate_requests_per_model_per_day", "limit_name": "GenerateRequestsPerDayPerProjectPerModel", "model": "gemini-2.5-pro-preview-tts"}},
     "points": [{"value": {"int64Value": "3"}}]}]}
calls = []


def fake_get(url, params=None):
    calls.append(url)
    if "serviceusage" in url:
        return LIMITS
    if "monitoring" in url:
        ok("net_usage" in params["filter"] and params["interval.startTime"].endswith("Z") and params["aggregation.perSeriesAligner"] == "ALIGN_SUM", "usage query asks Monitoring for net_usage since Pacific midnight")
        return USAGE
    raise AssertionError(url)


gq._get_json = fake_get
pool = [M, "gemini-2.5-pro-preview-tts", "gemini-2.5-flash-preview-tts"]
c = gq.cloud(pool, refresh=True)
ok(c["configured"] and c["error"] is None and c["limits_ok"] and c["usage_ok"], "cloud(): configured, both halves worked")
m = c["models"]
ok(m[M]["per_day_limit"] == 250 and m[M]["per_minute_limit"] == 30, "real day + minute limit matched to the model (token quota and global bucket ignored)")
ok(m[M]["used_today"] == 22, "real usage = sum of the day's points")
ok(m["gemini-2.5-pro-preview-tts"]["per_day_limit"] == 50 and m["gemini-2.5-pro-preview-tts"]["used_today"] == 3, "second model matched separately")
ok(m["gemini-2.5-flash-preview-tts"] == {"per_day_limit": None, "per_minute_limit": None, "used_today": None, "ambiguous": False}, "a model Google does not mention stays empty")
n = len(calls)
gq.cloud(pool)
ok(len(calls) == n, "answers are cached (no new Google calls)")

# ambiguity: free + paid metric both match -> biggest shown but flagged
amb = [{"metric": "x/requests_a", "display": "", "unit": "1/d/{project}/{model}", "limit_name": "d", "dimensions": {"model": M}, "limit": 100},
       {"metric": "x/requests_b", "display": "", "unit": "1/d/{project}/{model}", "limit_name": "d", "dimensions": {"model": M}, "limit": 250}]
r = gq.per_model([M], amb, [])[M]
ok(r["per_day_limit"] == 250 and r["ambiguous"] is True, "several different limits -> biggest, flagged ambiguous")

# real shape (2026-11-14): Google lists every tier's limits for every project, and drops "-preview" from the model name
def row(metric, display, unit, model, limit):
    return {"metric": "generativelanguage.googleapis.com/" + metric, "display": display, "unit": unit, "limit_name": "x", "dimensions": {"model": model}, "limit": limit}
D, MIN = "1/d/{project}/{model}", "1/min/{project}/{model}"
real = []
for mod, t1 in (("gemini-2.5-flash-tts", (10, 100)), ("gemini-3.8-flash", (1000, 10000))):
    real += [row("generate_content_free_tier_requests", "in the free tier.", MIN, mod, 3), row("generate_content_free_tier_requests", "in the free tier.", D, mod, 10),
             row("generate_requests_per_model", "requests per model (paid tier)", MIN, mod, t1[0]), row("generate_requests_per_model_per_day", "requests per model per day", D, mod, t1[1]),
             row("generate_content_paid_tier_2_requests", "(paid tier 2)", MIN, mod, 1000), row("generate_content_paid_tier_2_requests", "(paid tier 2)", D, mod, 10000),
             row("generate_content_paid_tier_2_requests_prio", "(paid tier 2) (priority)", D, mod, 3000),
             row("generate_content_paid_tier_3_requests", "(paid tier 3)", MIN, mod, 1000), row("generate_content_paid_tier_3_requests", "(paid tier 3)", D, mod, -1),
             row("generate_content_paid_tier_input_token_count", "input token count", MIN, mod, 10000)]
os.environ.pop("GEMINI_TIER", None)
r = gq.per_model(["gemini-2.5-flash-preview-tts", "gemini-3.8-flash-tts"], real, [])
p_ = r["gemini-2.5-flash-preview-tts"]
ok(p_["per_day_limit"] == 100 and p_["per_minute_limit"] == 10 and p_["ambiguous"] is False and p_["tier"] == "1", f"all tiers listed: OUR tier's limit (tier 1 by default) is shown, '-preview' name matched ({p_['per_day_limit']}/day)")
ok(p_["tiers"]["2"] == {"day": 10000, "minute": 1000} and p_["tiers"]["3"]["day"] == -1 and p_["tiers"]["free"]["day"] == 10, "every tier's limits are kept for the page (priority rows ignored)")
ok(r["gemini-3.8-flash-tts"]["per_day_limit"] is None, "another model's rows (gemini-3.8-flash) are not taken for gemini-3.8-flash-tts")
os.environ["GEMINI_TIER"] = "2"
ok(gq.per_model(["gemini-2.5-flash-preview-tts"], real, [])["gemini-2.5-flash-preview-tts"]["per_day_limit"] == 10000, "GEMINI_TIER=2 shows the tier 2 limit")
os.environ.pop("GEMINI_TIER", None)

# raw view + half failing
raw = gq.raw()
ok(len(raw["limits"]) == 4 and all("request" in (x["metric"] + x["display"]).lower() for x in raw["limits"]) and len(raw["usage"]) == 2, "raw(): request quotas only, usage rows kept")


def usage_denied(url, params=None):
    if "monitoring" in url:
        raise RuntimeError("Google answered 403: PERMISSION_DENIED Monitoring API has not been used in project my-proj")
    return LIMITS


gq.clear_cache()
gq._get_json = usage_denied
c = gq.cloud(pool, refresh=True)
ok(c["limits_ok"] and not c["usage_ok"] and "PERMISSION_DENIED" in c["error"] and c["models"][M]["per_day_limit"] == 250 and c["models"][M]["used_today"] is None,
   "usage 403 -> limits still shown, error text explains it")

# not configured
os.environ["GCP_PROJECT_ID"] = ""
ok(gq.cloud(pool)["configured"] is False and gq.raw()["configured"] is False, "no project -> not configured, no Google call")
os.environ["GCP_PROJECT_ID"] = "my-proj"

# ---- through the admin API ----
gq.clear_cache()
gq._get_json = fake_get
gq._list_models = lambda: {M: {"input_token_limit": 8192, "output_token_limit": 16384, "actions": ["generateContent"]}}
with Session() as s:
    s.add(User(email="boss@x.com", password_hash=auth.hash_password("password1"), is_admin=True, is_superadmin=True))
    s.commit()
client = TestClient(app)
tok = client.post("/api/auth/login", json={"email": "boss@x.com", "password": "password1"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}
t = client.get("/api/admin/tts?refresh=true", headers=H).json()
mm = {x["model"]: x for x in t["models"]}
ok(t["cloud"]["configured"] and t["cloud"]["project"] == "my-proj" and t["verify_error"] is None, "/tts reports cloud connection")
ok(mm[M]["google"]["exists"] and mm[M]["google"]["input_token_limit"] == 8192, "/tts: model verified with Google + token limits")
ok(mm["gemini-2.5-pro-preview-tts"]["google"] == {"exists": False}, "/tts: pool model missing for the key is flagged")
ok(mm[M]["seen_limit"]["per_day"] == 100 and mm[M]["cloud"]["per_day_limit"] == 250 and mm[M]["cloud"]["used_today"] == 22, "/tts: learned limit, real limit and real usage side by side")
ok(client.get("/api/admin/google-quota", headers=H).json()["configured"] is True, "/google-quota raw endpoint")
ok(client.get("/api/admin/google-quota").status_code == 401, "/google-quota needs a token")


def boom():
    raise RuntimeError("API key invalid")


gq.clear_cache()
gq._list_models = boom
t = client.get("/api/admin/tts", headers=H).json()
ok("API key invalid" in t["verify_error"] and t["models"][0]["google"] is None, "/tts: model check failing is reported, not raised")
print("all google quota tests passed")
