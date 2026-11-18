"""Offline test: /api/files answers HTTP Range (206) so a video can be skipped in the browser. Run: python test_range.py"""
import os, tempfile
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake", DATABASE_URL=f"sqlite:///{tmp}/t.db", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="")
for d in ("data", "up", "out"): os.makedirs(f"{tmp}/{d}", exist_ok=True)
from fastapi.testclient import TestClient
import auth, main

def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c: raise SystemExit(1)

body = bytes(range(256)) * 20000          # 5.12 MB, more than one 1 MB chunk
name = "recap_output_abc.mp4"
open(f"{tmp}/out/{name}", "wb").write(body)
exp, sig = auth.sign_file(name, 600)
url = f"/api/files/{name}?exp={exp}&sig={sig}"
c = TestClient(main.app)
r = c.get(url)
ok(r.status_code == 200 and r.content == body and r.headers["accept-ranges"] == "bytes", "no Range: whole file, Accept-Ranges announced")
r = c.get(url, headers={"Range": "bytes=1000-1999"})
ok(r.status_code == 206 and r.content == body[1000:2000] and r.headers["content-range"] == f"bytes 1000-1999/{len(body)}" and r.headers["content-length"] == "1000", "bytes=1000-1999")
r = c.get(url, headers={"Range": "bytes=3000000-"})
ok(r.status_code == 206 and r.content == body[3000000:] and r.headers["content-range"] == f"bytes 3000000-{len(body)-1}/{len(body)}", "open-ended range across several chunks")
r = c.get(url, headers={"Range": "bytes=-500"})
ok(r.status_code == 206 and r.content == body[-500:], "suffix range (the last 500 bytes: MP4 index at the end)")
r = c.get(url, headers={"Range": f"bytes=0-{len(body) * 2}"})
ok(r.status_code == 206 and r.content == body, "end past the file is cut to the file")
r = c.get(url, headers={"Range": f"bytes={len(body) + 5}-"})
ok(r.status_code == 416 and r.headers["content-range"] == f"bytes */{len(body)}", "start past the end: 416")
r = c.get(url, headers={"Range": "bytes=abc"})
ok(r.status_code == 200 and r.content == body, "garbage Range header: whole file")
r = c.get(url + "&dl=1", headers={"Range": "bytes=0-9"})
ok(r.status_code == 206 and "attachment" in r.headers.get("content-disposition", ""), "download link keeps its file name with a range")
r = c.get(f"/api/files/{name}?exp={exp}&sig=bad", headers={"Range": "bytes=0-9"})
ok(r.status_code == 403, "a bad signature is still refused")
print("ALL OK")
