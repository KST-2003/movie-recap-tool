"""Offline test: the interactive API docs (/docs, /redoc, /openapi.json) are OFF by default (security fix: OWASP A05 finding
-- they were publicly reachable with no login and handed out a full map of every route, including the 10 admin ones).
API_DOCS=true turns them back on for local debugging; this test checks the default (API_DOCS unset).
Run: python test_docs_disabled.py"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(PASSWORD_SCRYPT_LOG2_N="10", PASSWORD_SCRYPT_P="1", AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data",
                  UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake", GEMINI_API_KEY="x", DATABASE_URL=f"sqlite:///{tmp}/t.db",
                  GLOBAL_DAILY_MINUTES="0", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", ADMIN_WEBHOOK_URL="")
os.environ.pop("API_DOCS", None)  # the thing under test: nobody set it

import config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


ok(config.API_DOCS is False, "config.API_DOCS defaults to off when the env var is unset")
client = TestClient(main.app)
for path in ("/docs", "/redoc", "/openapi.json"):
    r = client.get(path)
    ok(r.status_code == 404, f"{path} -> {r.status_code} (must be 404 by default: no route map handed out for free)")
ok(client.get("/health").status_code == 200, "the app itself still works with docs off")
print("ALL OK")
