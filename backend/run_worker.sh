#!/bin/sh
# One worker = one job at a time. Run N of these (on any machines that can reach Redis, the database and storage).
# SimpleWorker runs jobs in-process: avoids fork() problems with torch/OpenCV on macOS and saves memory.
cd "$(dirname "$0")"
RQ=./venv/bin/rq; [ -x "$RQ" ] || RQ=rq
exec $RQ worker recap --url "${REDIS_URL:-redis://localhost:6379}" --worker-class rq.SimpleWorker
