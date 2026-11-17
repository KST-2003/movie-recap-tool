"""Over-the-air (OTA) updates for the Capacitor phone app: new WEB files (the React app) without a store release.
The app (plugin @capgo/capacitor-updater, configured in frontend/capacitor.config.json) asks POST /api/ota/update every time it comes to the front,
downloads the zip we name, checks its sha256, and starts it on the next launch; if the new bundle does not call notifyAppReady() in time, the plugin
goes back to the old one by itself. Everything is hosted by us (no Capgo account): files live in OTA_DIR (default DATA_DIR/ota):
    latest.json  {"version": "ota-20261117-1500", "file": "ota-20261117-1500.zip", "checksum": "<sha256 hex>", "enabled": true,
                  "min_build": {"ios": 1, "android": 1}}
    <file>.zip   the built web app (index.html at the top of the zip)
`frontend/scripts/publish-ota.mjs` builds, zips, uploads and writes latest.json. `enabled: false` (or deleting latest.json) = no updates.
min_build: the lowest NATIVE build number that may take this bundle (a bundle that needs a plugin an old app does not have must not go to it).
Only web files can change this way: native code, plugins and permissions still need a store release."""
import json
import os
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from config import DATA_DIR

OTA_DIR = os.getenv("OTA_DIR", os.path.join(DATA_DIR, "ota"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "https://movie-recap.bronicon.co").rstrip("/")
_FILE = re.compile(r"^[A-Za-z0-9._-]{1,120}\.zip$")
NO_UPDATE = {"error": "no_new_version_available", "message": "No new version available"}

router = APIRouter()


def _latest() -> dict | None:
    try:
        with open(os.path.join(OTA_DIR, "latest.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("enabled", True):
        return None
    if not (isinstance(data.get("version"), str) and isinstance(data.get("file"), str) and _FILE.match(data["file"])):
        return None
    if not os.path.isfile(os.path.join(OTA_DIR, data["file"])):
        return None
    return data


def _num(value) -> int:
    try:
        return int(str(value).split(".")[0])
    except (TypeError, ValueError):
        return 0


@router.post("/api/ota/update")
async def ota_update(request: Request):
    """The plugin's update check. Answers the bundle to use, or `no_new_version_available`."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    latest = _latest()
    if latest is None or body.get("version_name") == latest["version"]:
        return NO_UPDATE
    platform = body.get("platform") if body.get("platform") in ("ios", "android") else "ios"
    min_build = (latest.get("min_build") or {}).get(platform, 0)
    if _num(body.get("version_build")) < _num(min_build):   # this app's native part is too old for the bundle
        return NO_UPDATE
    out = {"version": latest["version"], "url": f"{PUBLIC_URL}/api/ota/bundles/{latest['file']}"}
    if latest.get("checksum"):
        out["checksum"] = latest["checksum"]
    return out


@router.get("/api/ota/bundles/{name}")
def ota_bundle(name: str):
    path = os.path.join(OTA_DIR, name)
    if not _FILE.match(name) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="application/zip", headers={"Cache-Control": "public, max-age=31536000, immutable"})
