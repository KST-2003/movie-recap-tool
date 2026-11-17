"""Offline test: the OTA update endpoint for the phone app. Run: python test_ota.py"""
import json
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake",
                  DATABASE_URL=f"sqlite:///{tmp}/t.db", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", PUBLIC_URL="https://example.test")
for d in ("data", "up", "out", "data/ota"):
    os.makedirs(f"{tmp}/{d}", exist_ok=True)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


c = TestClient(main.app)
ota = f"{tmp}/data/ota"
ask = lambda **kw: c.post("/api/ota/update", json={"platform": "ios", "version_name": "builtin", "version_build": "5", **kw}).json()
ok(ask()["error"] == "no_new_version_available", "no latest.json: no update")
open(f"{ota}/ota-1.zip", "wb").write(b"PK-zip")
json.dump({"version": "ota-1", "file": "ota-1.zip", "checksum": "ab" * 32, "enabled": True, "min_build": {"ios": 3, "android": 1}}, open(f"{ota}/latest.json", "w"))
r = ask()
ok(r["version"] == "ota-1" and r["url"] == "https://example.test/api/ota/bundles/ota-1.zip" and r["checksum"] == "ab" * 32, "new bundle offered with url + checksum")
ok(ask(version_name="ota-1")["error"] == "no_new_version_available", "already on it: no update")
ok(ask(version_build="2")["error"] == "no_new_version_available", "native build below min_build: no update")
ok(ask(platform="android", version_build="1")["version"] == "ota-1", "android min_build is its own")
ok(c.post("/api/ota/update", content=b"not json").status_code == 200, "garbage body answered")
b = c.get("/api/ota/bundles/ota-1.zip")
ok(b.status_code == 200 and b.content == b"PK-zip", "the zip is served")
ok(c.get("/api/ota/bundles/..%2Fapp.db").status_code == 404 and c.get("/api/ota/bundles/latest.json").status_code == 404, "only zips by plain name")
json.dump({"version": "ota-1", "file": "ota-1.zip", "enabled": False}, open(f"{ota}/latest.json", "w"))
ok(ask()["error"] == "no_new_version_available", "enabled:false = kill switch")
json.dump({"version": "ota-2", "file": "missing.zip", "enabled": True}, open(f"{ota}/latest.json", "w"))
ok(ask()["error"] == "no_new_version_available", "latest.json pointing at a missing file: no update")
json.dump({"version": "x", "file": "../../etc/passwd", "enabled": True}, open(f"{ota}/latest.json", "w"))
ok(ask()["error"] == "no_new_version_available", "bad file name refused")
print("ALL OK")
