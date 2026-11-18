"""HTTP Range support for file downloads. The installed Starlette (0.36) ignores the Range header and always sends the whole file, so a browser
could only jump to a part of a video it had already downloaded (and Safari / iOS may refuse to play or seek at all). Newer Starlette has this
built in; until FastAPI is upgraded we answer ranges ourselves."""
import os
import re
from typing import Iterator

from fastapi import Request
from fastapi.responses import FileResponse, Response, StreamingResponse

CHUNK = 1024 * 1024
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _slice(path: str, start: int, end: int) -> Iterator[bytes]:
    with open(path, "rb") as f:
        f.seek(start)
        left = end - start + 1
        while left > 0:
            data = f.read(min(CHUNK, left))
            if not data:
                break
            left -= len(data)
            yield data


def file_response(request: Request, path: str, media_type: str, filename: str | None = None):
    """200 with the whole file, or 206 with the asked bytes (one range: what browsers send for <video>). Always says Accept-Ranges."""
    size = os.path.getsize(path)
    spec = (request.headers.get("range") or "").strip()
    m = _RANGE.match(spec) if spec else None
    if m and (m.group(1) or m.group(2)):
        if m.group(1) == "":                       # "-500" = the last 500 bytes
            n = int(m.group(2))
            start, end = max(size - n, 0), size - 1
        else:
            start = int(m.group(1))
            end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
        if size == 0 or start >= size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})
        headers = {"Accept-Ranges": "bytes", "Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)}
        if filename:
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return StreamingResponse(_slice(path, start, end), status_code=206, media_type=media_type, headers=headers)
    if spec:   # a Range we do not understand (several ranges, other units, garbage): the whole file, the same on every Starlette version
        headers = {"Accept-Ranges": "bytes", "Content-Length": str(size)}
        if filename:
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return StreamingResponse(_slice(path, 0, size - 1) if size else iter(()), status_code=200, media_type=media_type, headers=headers)
    return FileResponse(path, media_type=media_type, filename=filename, headers={"Accept-Ranges": "bytes"})
