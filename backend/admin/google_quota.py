"""What Google itself says about our Gemini voice models (admin "Voice models" page). Three sources, each optional:

1. models.list with the API key -> the model really exists for this key, its token limits (no setup).
2. Service Usage API (consumerQuotaMetrics) -> the REAL request limits of the project, per model (needs a service account).
3. Cloud Monitoring API (serviceruntime quota metrics) -> the REAL usage of the quota day (same service account).

Setup for 2 and 3 (see .env.example): GCP_PROJECT_ID + GCP_SERVICE_ACCOUNT_FILE. The service account needs the roles
"Service Usage Viewer" and "Monitoring Viewer"; the "Service Usage API" and "Cloud Monitoring API" must be enabled.
Nothing here ever raises into the page: a failure becomes an `error` text next to the data that did work.
Google does not document the exact metric labels for the Gemini API, so the parsing is generic (a model is matched by its
name appearing in a quota's dimensions/labels) and `raw()` shows exactly what Google returned, to tune the matching."""
import os
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SERVICE = "generativelanguage.googleapis.com"
SCOPES = ["https://www.googleapis.com/auth/monitoring.read", "https://www.googleapis.com/auth/cloud-platform.read-only"]
TTL_MODELS, TTL_LIMITS, TTL_USAGE = 600, 600, 60   # seconds each answer is reused

_lock = threading.Lock()
_cache: dict = {}
_session = None


def _cached(key, ttl, fn, refresh=False):
    with _lock:
        hit = _cache.get(key)
        if hit and not refresh and time.time() - hit[0] < ttl:
            return hit[1]
    value = fn()
    with _lock:
        _cache[key] = (time.time(), value)
    return value


def clear_cache():
    with _lock:
        _cache.clear()


# ---------- 1. does the model exist for this API key ----------

def _list_models() -> dict:
    import gemini_tts
    found = {}
    for m in gemini_tts._get_client().models.list():
        found[m.name.replace("models/", "")] = {
            "input_token_limit": m.input_token_limit, "output_token_limit": m.output_token_limit,
            "actions": list(m.supported_actions or [])}
    return found


def verify_models(refresh: bool = False) -> dict:
    """{"models": {name: {...}}, "error": str|None}. Cached; never raises."""
    def load():
        try:
            return {"models": _list_models(), "error": None}
        except Exception as exc:
            return {"models": {}, "error": f"{exc.__class__.__name__}: {str(exc)[:200]}"}
    return _cached("models", TTL_MODELS, load, refresh)


# ---------- service account access (2 and 3) ----------

def project() -> str:
    return os.getenv("GCP_PROJECT_ID", "").strip()


def _key_file() -> str:
    return os.getenv("GCP_SERVICE_ACCOUNT_FILE") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or ""


def configured() -> bool:
    return bool(project() and _key_file() and os.path.exists(_key_file()))


def _short_error(resp) -> str:
    try:
        err = resp.json().get("error", {})
        return f"{err.get('status', '')} {err.get('message', '')}".strip()[:400]
    except Exception:
        return resp.text[:300]


def _get_json(url: str, params: dict | None = None) -> dict:
    """The only function that talks to Google Cloud (tests replace it)."""
    global _session
    if _session is None:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
        _session = AuthorizedSession(service_account.Credentials.from_service_account_file(_key_file(), scopes=SCOPES))
    resp = _session.get(url, params=params, timeout=20)
    if resp.status_code >= 400:
        raise RuntimeError(f"Google answered {resp.status_code}: {_short_error(resp)}")
    return resp.json()


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------- 2. the real limits (Service Usage API) ----------

def _fetch_limits() -> list[dict]:
    url = f"https://serviceusage.googleapis.com/v1beta1/projects/{project()}/services/{SERVICE}/consumerQuotaMetrics"
    rows, token = [], None
    for _ in range(20):
        data = _get_json(url, {"view": "FULL", "pageSize": 200, **({"pageToken": token} if token else {})})
        for metric in data.get("metrics", []):
            for lim in metric.get("consumerQuotaLimits", []):
                for bucket in lim.get("quotaBuckets", []):
                    rows.append({"metric": metric.get("metric", ""), "display": metric.get("displayName", ""),
                                 "unit": lim.get("unit") or metric.get("unit") or "", "limit_name": (lim.get("name") or "").split("/")[-1],
                                 "dimensions": bucket.get("dimensions") or {}, "limit": _int(bucket.get("effectiveLimit"))})
        token = data.get("nextPageToken")
        if not token:
            break
    return rows


# ---------- 3. the real usage (Cloud Monitoring API) ----------

def quota_day_start() -> datetime:
    """Google's daily quotas reset at midnight Pacific time."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _fetch_usage() -> list[dict]:
    start, end = quota_day_start(), datetime.now(timezone.utc)
    params = {
        "filter": ('metric.type = "serviceruntime.googleapis.com/quota/rate/net_usage" AND resource.type = "consumer_quota" '
                   f'AND resource.labels.service = "{SERVICE}"'),
        "interval.startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "interval.endTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "aggregation.alignmentPeriod": f"{max(60, int((end - start).total_seconds()))}s",
        "aggregation.perSeriesAligner": "ALIGN_SUM", "view": "FULL"}
    url = f"https://monitoring.googleapis.com/v3/projects/{project()}/timeSeries"
    rows, token = [], None
    for _ in range(20):
        data = _get_json(url, {**params, **({"pageToken": token} if token else {})})
        for series in data.get("timeSeries", []):
            labels = {**(series.get("resource", {}).get("labels") or {}), **(series.get("metric", {}).get("labels") or {})}
            used = 0.0
            for point in series.get("points", []):
                v = point.get("value", {})
                used += float(v.get("int64Value") or v.get("doubleValue") or 0)
            rows.append({"quota_metric": labels.get("quota_metric", ""), "limit_name": labels.get("limit_name", ""),
                         "labels": labels, "used": int(round(used))})
        token = data.get("nextPageToken")
        if not token:
            break
    return rows


# ---------- putting it together ----------

def _scope(text: str):
    t = text.lower()
    if "/d/" in t or "day" in t:
        return "day"
    if "/min/" in t or "minute" in t:
        return "minute"
    return None


def _mentions(model: str, values) -> bool:
    return model.lower() in " ".join(str(v) for v in values).lower()


def per_model(pool: list[str], limits: list[dict], usage: list[dict]) -> dict:
    """{model: {per_day_limit, per_minute_limit, used_today, ambiguous}} from whatever Google returned.
    ambiguous = several different limits matched (e.g. free tier + paid tier metrics): then the biggest is shown and flagged."""
    out = {}
    for model in pool:
        found = {"day": set(), "minute": set()}
        for r in limits:
            if r["limit"] is None or "request" not in f"{r['metric']} {r['display']} {r['limit_name']}".lower():
                continue
            if not _mentions(model, r["dimensions"].values()):
                continue
            scope = _scope(f"{r['unit']} {r['limit_name']}")
            if scope:
                found[scope].add(r["limit"])
        used = [u["used"] for u in usage
                if "request" in f"{u['quota_metric']} {u['limit_name']}".lower() and _scope(f"{u['quota_metric']} {u['limit_name']}") == "day"
                and _mentions(model, u["labels"].values())]
        out[model] = {"per_day_limit": max(found["day"]) if found["day"] else None,
                      "per_minute_limit": max(found["minute"]) if found["minute"] else None,
                      "used_today": sum(used) if used else None,
                      "ambiguous": len(found["day"]) > 1 or len(found["minute"]) > 1}
    return out


def cloud(pool: list[str], refresh: bool = False) -> dict:
    """{"configured", "project", "error", "limits_ok", "usage_ok", "models": {...}}; each half can fail on its own."""
    if not configured():
        return {"configured": False, "project": project(), "error": None, "limits_ok": False, "usage_ok": False, "models": {}}
    errors, limits, usage = [], [], []
    try:
        limits = _cached("limits", TTL_LIMITS, _fetch_limits, refresh)
    except Exception as exc:
        errors.append(f"Quota limits: {str(exc)[:300]}")
    try:
        usage = _cached("usage", TTL_USAGE, _fetch_usage, refresh)
    except Exception as exc:
        errors.append(f"Usage: {str(exc)[:300]}")
    return {"configured": True, "project": project(), "error": " | ".join(errors) or None,
            "limits_ok": bool(limits), "usage_ok": not any(e.startswith("Usage") for e in errors),
            "models": per_model(pool, limits, usage)}


def raw(refresh: bool = False) -> dict:
    """Everything Google returned, unmatched, so the matching can be checked by eye."""
    if not configured():
        return {"configured": False, "limits": [], "usage": [], "error": None}
    errors, limits, usage = [], [], []
    try:
        limits = _cached("limits", TTL_LIMITS, _fetch_limits, refresh)
    except Exception as exc:
        errors.append(f"Quota limits: {str(exc)[:300]}")
    try:
        usage = _cached("usage", TTL_USAGE, _fetch_usage, refresh)
    except Exception as exc:
        errors.append(f"Usage: {str(exc)[:300]}")
    # only rows about requests (token quotas are noise here), biggest first
    limits = [r for r in limits if "request" in f"{r['metric']} {r['display']} {r['limit_name']}".lower()]
    return {"configured": True, "project": project(), "error": " | ".join(errors) or None,
            "limits": sorted(limits, key=lambda r: (r["metric"], -(r["limit"] or 0)))[:300], "usage": sorted(usage, key=lambda u: -u["used"])[:300]}
