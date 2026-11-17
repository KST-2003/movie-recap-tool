"""Presets = saved settings for a NEW video (format, look, subtitle style, voice, output...), picked with one button on the Create page.
- A user keeps up to MAX_USER_PRESETS of their own (private).
- Admins and the superadmin make presets for everybody: draft = only admins see it, published ("submitted") = every user can pick it.
The settings are a whitelist of the upload form's fields (`clean_settings`): unknown keys are dropped, bad values refused. The logo FILE and
hand-drawn blur boxes belong to one video and are not stored. Users: /api/presets. Admins: /api/admin/presets (audit-logged)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

import auth
from admin.routes import _audit, _iso, require_admin
from db import Job, Preset, Session, User, utcnow

MAX_USER_PRESETS = 5
STATUSES = ("draft", "published")
CAPTION_KEYS = {"font": str, "size": float, "color": str, "outline": str, "bg": str, "bg_opacity": float, "position": str, "y": float}
_HEX = lambda v: isinstance(v, str) and len(v) == 7 and v[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in v[1:])


def _num(lo, hi):
    return lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi


def _in(*values):
    return lambda v: v in values


_bool = lambda v: isinstance(v, bool)
RULES = {
    "aspect": _in("original", "9:16", "1:1", "4:5", "16:9"), "fitMode": _in("blur", "crop"), "resolution": _in("720", "1080"),
    "videoSpeed": _num(0.5, 2), "brightness": _num(-0.5, 0.5), "contrast": _num(0.5, 1.5), "saturation": _num(0, 2),
    "logoPosition": _in("top-left", "top-right", "bottom-left", "bottom-right", "center"), "logoSize": _num(0.05, 0.5), "logoOnTop": _bool,
    "blurSubtitles": _bool, "watermark": _bool, "flip": _bool,
    "voiceQuality": _in("standard", "premium"), "filmMode": _in("recap", "full"), "outputKind": _in("dub", "voice", "subtitles"),
    "bgMode": _in("separate", "original", "off"), "emotionOn": _bool, "softMusic": _bool,
}


def clean_caption(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    out = {}
    for k, v in raw.items():
        if k not in CAPTION_KEYS or v is None:
            continue
        if k in ("color", "bg") and not _HEX(v):
            continue
        if k == "outline" and v != "" and not _HEX(v):
            continue
        if k in ("size", "bg_opacity", "y") and not _num(0, 2)(v):
            continue
        if k in ("font", "position") and (not isinstance(v, str) or len(v) > 20):
            continue
        out[k] = v
    return out or None


def clean_settings(raw) -> dict:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="The preset settings are missing.")
    out = {}
    for k, ok in RULES.items():
        if k in raw and raw[k] is not None:
            if not ok(raw[k]):
                raise HTTPException(status_code=400, detail=f"Bad value for {k}.")
            out[k] = raw[k]
    if raw.get("voiceType"):
        import looks
        if not isinstance(raw["voiceType"], str) or not looks.valid(raw["voiceType"]):
            raise HTTPException(status_code=400, detail="Unknown voice.")
        out["voiceType"] = raw["voiceType"]
    cap = clean_caption(raw.get("captionStyle"))
    if cap:
        out["captionStyle"] = cap
    return out


def _name(text) -> str:
    text = (text or "").strip()
    if not text or len(text) > 40:
        raise HTTPException(status_code=400, detail="Give the preset a name (up to 40 characters).")
    return text


class PresetBody(BaseModel):
    name: str = Field(max_length=200)
    settings: dict
    status: str | None = None          # admin presets: draft | published


def row(p: Preset, admin: bool = False) -> dict:
    d = {"id": p.id, "name": p.name, "settings": p.settings or {}, "updated_at": _iso(p.updated_at)}
    if admin:
        d.update({"status": p.status, "created_by": p.created_by, "created_at": _iso(p.created_at)})
    return d


router = APIRouter()
admin_router = APIRouter(prefix="/api/admin/presets", dependencies=[Depends(require_admin)])


# ---------- users ----------


def settings_from_params(params: dict) -> dict:
    """The preset-shaped settings of a finished upload's job params ("use my previous settings"). Anything that does not pass the same checks as a preset is left out."""
    p = params or {}
    raw = {"aspect": p.get("aspect"), "fitMode": p.get("fit_mode"), "resolution": str(p.get("resolution") or "") or None, "videoSpeed": p.get("video_speed"),
           "brightness": p.get("brightness"), "contrast": p.get("contrast"), "saturation": p.get("saturation"), "logoPosition": p.get("logo_position"),
           "logoSize": p.get("logo_size"), "logoOnTop": p.get("logo_above_subtitle"), "blurSubtitles": p.get("blur_subtitles"), "watermark": p.get("remove_watermark"),
           "flip": p.get("enable_flip"), "voiceQuality": p.get("voice_quality"), "voiceType": p.get("voice_type"), "filmMode": p.get("mode"),
           "outputKind": "subtitles" if p.get("output") == "subtitles" else ("dub" if p.get("enable_subtitles", True) else "voice"),
           "bgMode": p.get("background") or None, "emotionOn": p.get("emotion"), "softMusic": p.get("soft_music"), "captionStyle": p.get("caption_style")}
    out = {}
    for k, v in raw.items():
        if v is None:
            continue
        try:
            out.update(clean_settings({k: v}))
        except HTTPException:
            pass
    return out


@router.get("/api/presets/last")
def last_settings(user: User = Depends(auth.current_user)):
    """The settings of the user's most recent NEW video (not an editor re-render): "Use previous settings" on the Create page."""
    with Session() as s:
        jobs = s.execute(select(Job).where(Job.user_id == user.id, Job.status != "cancelled").order_by(Job.created_at.desc()).limit(40)).scalars().all()
        job = next((j for j in jobs if not (j.params or {}).get("edit") and (j.params or {}).get("aspect")), None)
        if job is None:
            return {"settings": None}
        return {"settings": settings_from_params(job.params), "title": (job.params or {}).get("filename") or "", "created_at": _iso(job.created_at)}

@router.get("/api/presets")
def my_presets(user: User = Depends(auth.current_user)):
    with Session() as s:
        mine = s.execute(select(Preset).where(Preset.user_id == user.id).order_by(Preset.id)).scalars().all()
        shared = s.execute(select(Preset).where(Preset.user_id.is_(None), Preset.status == "published").order_by(Preset.id)).scalars().all()
        return {"max": MAX_USER_PRESETS, "mine": [row(p) for p in mine], "shared": [row(p) for p in shared]}


@router.post("/api/presets")
def create_preset(body: PresetBody, user: User = Depends(auth.current_user)):
    name, settings = _name(body.name), clean_settings(body.settings)
    with Session() as s:
        if s.execute(select(func.count()).select_from(Preset).where(Preset.user_id == user.id)).scalar_one() >= MAX_USER_PRESETS:
            raise HTTPException(status_code=400, detail=f"You can keep up to {MAX_USER_PRESETS} presets. Delete one to make a new one.")
        p = Preset(user_id=user.id, name=name, settings=settings, status="published", created_by=user.email)
        s.add(p)
        s.commit()
        return row(p)


@router.put("/api/presets/{preset_id}")
def update_preset(preset_id: int, body: PresetBody, user: User = Depends(auth.current_user)):
    name, settings = _name(body.name), clean_settings(body.settings)
    with Session() as s:
        p = s.get(Preset, preset_id)
        if p is None or p.user_id != user.id:
            raise HTTPException(status_code=404, detail="Unknown preset.")
        p.name, p.settings, p.updated_at = name, settings, utcnow()
        s.commit()
        return row(p)


@router.delete("/api/presets/{preset_id}")
def delete_preset(preset_id: int, user: User = Depends(auth.current_user)):
    with Session() as s:
        p = s.get(Preset, preset_id)
        if p is None or p.user_id != user.id:
            raise HTTPException(status_code=404, detail="Unknown preset.")
        s.delete(p)
        s.commit()
    return {"ok": True}


# ---------- admins: presets for everybody ----------

@admin_router.get("")
def admin_list():
    with Session() as s:
        rows = s.execute(select(Preset).where(Preset.user_id.is_(None)).order_by(Preset.id.desc())).scalars().all()
        return {"items": [row(p, True) for p in rows]}


@admin_router.post("")
def admin_create(body: PresetBody, admin: User = Depends(require_admin)):
    name, settings = _name(body.name), clean_settings(body.settings)
    status = body.status or "draft"
    if status not in STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status.")
    with Session() as s:
        p = Preset(user_id=None, name=name, settings=settings, status=status, created_by=admin.email)
        s.add(p)
        s.flush()
        _audit(s, admin, "preset.create", "preset", p.id, p.name, {"status": status})
        s.commit()
        return row(p, True)


@admin_router.put("/{preset_id}")
def admin_update(preset_id: int, body: PresetBody, admin: User = Depends(require_admin)):
    name, settings = _name(body.name), clean_settings(body.settings)
    with Session() as s:
        p = s.get(Preset, preset_id)
        if p is None or p.user_id is not None:
            raise HTTPException(status_code=404, detail="Unknown preset.")
        status = body.status or p.status
        if status not in STATUSES:
            raise HTTPException(status_code=400, detail="Unknown status.")
        changed = {}
        if p.name != name:
            changed["name"] = {"from": p.name, "to": name}
        if p.status != status:
            changed["status"] = {"from": p.status, "to": status}
        if (p.settings or {}) != settings:
            changed["settings"] = {"from": None, "to": "changed"}
        p.name, p.settings, p.status, p.updated_at = name, settings, status, utcnow()
        if changed:
            _audit(s, admin, "preset.update", "preset", p.id, p.name, changed)
        s.commit()
        return row(p, True)


@admin_router.delete("/{preset_id}")
def admin_delete(preset_id: int, admin: User = Depends(require_admin)):
    with Session() as s:
        p = s.get(Preset, preset_id)
        if p is None or p.user_id is not None:
            raise HTTPException(status_code=404, detail="Unknown preset.")
        _audit(s, admin, "preset.delete", "preset", p.id, p.name, {"status": p.status})
        s.delete(p)
        s.commit()
    return {"ok": True}
