"""Real token usage and cost per video.

Every Gemini text/audio answer carries token counts (`usage_metadata`, `interaction.usage`), and so do Claude answers. We add them up
per video (a context variable holds the current job id; `install()` makes worker threads inherit it), save the totals in
`Job.data["usage"]` and price them with the per-model USD prices the owner can edit in the admin dashboard (+ the USD->THB rate).
Cost is computed when it is READ, so fixing a price re-prices the whole history. Stored shape, per model name:
    {"calls": n, "in": text/other input tokens, "audio_in": ..., "out": output tokens incl. thinking, "audio_out": ..., "est": estimated calls}
Cloud Text-to-Speech answers carry no token counts: audio_out is estimated from the clip length (25 tokens/s, measured on
2026-11-09: 89 tokens for 3.69 s) and flagged `est`.
Limits: voice previews in the editor run outside a job and are not counted; prices change on 2027-01-01 (Google announced a doubling for
the 3.8 models) - edit them then."""
import contextvars
import threading
import time
from concurrent.futures import ThreadPoolExecutor

_job: contextvars.ContextVar[str | None] = contextvars.ContextVar("usage_job", default=None)
_lock = threading.Lock()
_acc: dict[str, dict[str, dict]] = {}
_flushed: dict[str, float] = {}
AUDIO_TOKENS_PER_SECOND = 25.0
CHARS_PER_TOKEN = 3.0

# USD per 1M tokens. Source: Google's AI Studio pricing page, read on 2026-11-09 (Standard tier). "in" = text input, "audio_in" falls
# back to "in", "out" = text output incl. thinking, "audio_out" = voice. The cloud/ rows are ASSUMED equal to the AI Studio price of the
# same model (not listed on that page): check Cloud's own pricing page. Claude is not listed: enter its price in the dashboard.
DEFAULT_PRICES = {
    "gemini-3.8-flash": {"in": 0.75, "out": 3.75},
    "gemini-3.1-flash-tts-preview": {"in": 1.00, "audio_out": 20.00},
    "gemini-2.5-flash-preview-tts": {"in": 0.50, "audio_out": 10.00},
    "gemini-3.8-flash-tts": {"in": 0.50, "audio_out": 9.00},
    "gemini-3.8-flash-lite-tts": {"in": 0.50, "audio_out": 6.00},
    "gemini-2.5-pro-preview-tts": {"in": 1.00, "audio_out": 20.00},
    "cloud/gemini-2.5-flash-tts": {"in": 0.50, "audio_out": 10.00},
    "cloud/gemini-2.5-pro-tts": {"in": 1.00, "audio_out": 20.00},
}
ASSUMED = {"cloud/gemini-2.5-flash-tts", "cloud/gemini-2.5-pro-tts"}


# ---------- recording ----------

def start(job_id: str | None):
    """Attribute everything this thread (and the threads it starts) sends to `job_id`."""
    _job.set(job_id)
    if job_id:
        with _lock:
            _acc.setdefault(job_id, {})


def current() -> str | None:
    return _job.get()


def add(model: str, *, inp=0, audio_in=0, out=0, audio_out=0, est=False, job_id: str | None = None):
    job_id = job_id or _job.get()
    if not job_id or not model:
        return
    with _lock:
        m = _acc.setdefault(job_id, {}).setdefault(model, {"calls": 0, "in": 0, "audio_in": 0, "out": 0, "audio_out": 0, "est": 0})
        m["calls"] += 1
        m["in"] += int(inp or 0)
        m["audio_in"] += int(audio_in or 0)
        m["out"] += int(out or 0)
        m["audio_out"] += int(audio_out or 0)
        m["est"] += 1 if est else 0


def record_generate_content(resp, model: str | None):
    """Gemini text / audio-understanding answer (response.usage_metadata)."""
    u = getattr(resp, "usage_metadata", None)
    if u is None:
        return
    audio_in = 0
    for d in getattr(u, "prompt_tokens_details", None) or []:
        if str(getattr(d, "modality", "")).upper().endswith("AUDIO"):
            audio_in += int(getattr(d, "token_count", 0) or 0)
    prompt = int(getattr(u, "prompt_token_count", 0) or 0) + int(getattr(u, "tool_use_prompt_token_count", 0) or 0)
    out = int(getattr(u, "candidates_token_count", 0) or 0) + int(getattr(u, "thoughts_token_count", 0) or 0)   # thinking is billed as output
    add(model or getattr(resp, "model_version", "") or "unknown", inp=max(prompt - audio_in, 0), audio_in=audio_in, out=out)


def record_interaction(interaction, model: str):
    """Gemini TTS answer (interaction.usage): text in, audio out."""
    u = getattr(interaction, "usage", None)
    if u is None:
        return
    text_in = sum(int(getattr(x, "tokens", 0) or 0) for x in (getattr(u, "input_tokens_by_modality", None) or []) if getattr(x, "modality", "") != "audio")
    audio_out = sum(int(getattr(x, "tokens", 0) or 0) for x in (getattr(u, "output_tokens_by_modality", None) or []) if getattr(x, "modality", "") == "audio")
    other_out = max(int(getattr(u, "total_output_tokens", 0) or 0) - audio_out, 0)
    add(model, inp=text_in or int(getattr(u, "total_input_tokens", 0) or 0), audio_out=audio_out, out=other_out)


def record_cloud_tts(model: str, text: str, audio_seconds: float):
    """Cloud Text-to-Speech has no token counts in its answer: estimate from the clip length (flagged)."""
    add(model, inp=len(text) / CHARS_PER_TOKEN, audio_out=audio_seconds * AUDIO_TOKENS_PER_SECOND, est=True)


def record_claude(msg):
    u = getattr(msg, "usage", None)
    if u is None:
        return
    inp = int(getattr(u, "input_tokens", 0) or 0) + int(getattr(u, "cache_creation_input_tokens", 0) or 0) + int(getattr(u, "cache_read_input_tokens", 0) or 0)
    add(getattr(msg, "model", None) or "claude", inp=inp, out=int(getattr(u, "output_tokens", 0) or 0))


def snapshot(job_id: str) -> dict:
    with _lock:
        return {m: dict(v) for m, v in _acc.get(job_id, {}).items()}


def flush(job_id: str | None, force: bool = False):
    """Save the running totals into the job (throttled to once per 5 s unless forced). Never raises."""
    if not job_id:
        return
    now = time.monotonic()
    if not force and now - _flushed.get(job_id, 0) < 5:
        return
    snap = snapshot(job_id)
    if not snap:
        return
    _flushed[job_id] = now
    try:
        from db import add_usage
        add_usage(job_id, snap)
    except Exception as exc:
        print(f"[usage] could not save usage of {job_id}: {exc}", flush=True)


def forget(job_id: str):
    with _lock:
        _acc.pop(job_id, None)
    _flushed.pop(job_id, None)


# ---------- pricing ----------

def prices() -> dict:
    """DEFAULT_PRICES overlaid with the owner's edits (admin Settings)."""
    from admin import settings as S
    out = {k: dict(v) for k, v in DEFAULT_PRICES.items()}
    for model, p in (S.prices() or {}).items():
        out[model] = {k: float(v) for k, v in p.items() if v is not None}
    return out


def _price_for(model: str, table: dict) -> dict | None:
    if model in table:
        return table[model]
    if model.startswith("cloud/") and model[6:] in table:
        return table[model[6:]]
    return None


def cost_thb(usage: dict | None, table: dict | None = None, usd_thb: float | None = None) -> dict:
    """-> {"thb": float, "complete": bool, "unpriced": [models], "estimated": bool}. Unpriced models add nothing and clear `complete`."""
    from admin import settings as S
    table = table if table is not None else prices()
    rate = usd_thb if usd_thb is not None else S.usd_thb()
    usd, unpriced, est = 0.0, [], False
    for model, u in (usage or {}).items():
        p = _price_for(model, table)
        if not p:
            unpriced.append(model)
            continue
        i = p.get("in", 0.0)
        usd += (u.get("in", 0) * i + u.get("audio_in", 0) * p.get("audio_in", i)
                + u.get("out", 0) * p.get("out", 0.0) + u.get("audio_out", 0) * p.get("audio_out", p.get("out", 0.0))) / 1e6
        est = est or bool(u.get("est"))
    return {"thb": usd * rate, "complete": not unpriced, "unpriced": unpriced, "estimated": est}


# ---------- installing the hooks ----------

_installed = False


def install():
    """Idempotent: worker threads inherit the job id, and every Gemini text / Claude call is counted. Recording never breaks a call."""
    global _installed
    if _installed:
        return
    _installed = True
    orig_submit = ThreadPoolExecutor.submit

    def submit(self, fn, /, *args, **kwargs):
        ctx = contextvars.copy_context()
        return orig_submit(self, ctx.run, fn, *args, **kwargs)
    ThreadPoolExecutor.submit = submit

    try:
        from google.genai import models as gm
        orig = gm.Models.generate_content

        def generate_content(self, *args, **kwargs):
            resp = orig(self, *args, **kwargs)
            try:
                record_generate_content(resp, kwargs.get("model") or (args[0] if args else None))
            except Exception:
                pass
            return resp
        gm.Models.generate_content = generate_content
    except Exception as exc:
        print(f"[usage] Gemini hook not installed: {exc}", flush=True)
    try:
        from anthropic.resources.messages import Messages
        orig_c = Messages.create

        def create(self, *args, **kwargs):
            msg = orig_c(self, *args, **kwargs)
            try:
                record_claude(msg)
            except Exception:
                pass
            return msg
        Messages.create = create
    except Exception:
        pass   # anthropic not installed / not used
