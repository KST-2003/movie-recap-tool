"""Signed file downloads: a <video>/<a download> tag cannot send an Authorization header, so finished results are
served from a short-lived HMAC-signed link instead (see auth.sign_file / services.quota.file_url)."""
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

import auth
from config import FILE_TTL_HOURS, OUTPUT_DIR

router = APIRouter(prefix="/api", tags=["files"])


@router.get("/files/{filename}")
def get_file(filename: str, exp: int, sig: str, dl: int = 0):
    name = os.path.basename(filename)
    if not auth.check_signature(name, exp, sig):
        raise HTTPException(status_code=403, detail="Link expired. Reload the page to get a new one.")
    path = os.path.join(OUTPUT_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found (results are kept for %g hours)." % FILE_TTL_HOURS)
    media_type = "application/x-subrip" if name.endswith(".srt") else "video/mp4"
    return FileResponse(path, media_type=media_type, filename=name if dl else None)
