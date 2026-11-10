"""File storage. local: files live on this machine (single server / dev).
s3: any S3-compatible bucket (DigitalOcean Spaces, AWS S3, MinIO) so API and worker machines can be separate.
Set STORAGE_BACKEND=s3 plus S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY, S3_ENDPOINT (e.g. https://sgp1.digitaloceanspaces.com), S3_REGION."""
import os
import time
import uuid

from config import OUTPUT_DIR, SIGNED_URL_SECONDS, UPLOAD_DIR

BACKEND = os.getenv("STORAGE_BACKEND", "local").lower()
BUCKET = os.getenv("S3_BUCKET", "")
_s3 = None


def _client():
    global _s3
    if _s3 is None:
        import boto3
        _s3 = boto3.client(
            "s3",
            endpoint_url=os.getenv("S3_ENDPOINT") or None,
            region_name=os.getenv("S3_REGION") or None,
            aws_access_key_id=os.getenv("S3_ACCESS_KEY"),
            aws_secret_access_key=os.getenv("S3_SECRET_KEY"),
        )
    return _s3


def put(local_path: str, prefix: str) -> str:
    """Store a local file; returns the key to keep in the database. The local copy is removed for s3."""
    if BACKEND != "s3":
        return local_path
    key = f"{prefix}/{uuid.uuid4().hex}{os.path.splitext(local_path)[1]}"
    _client().upload_file(local_path, BUCKET, key)
    os.remove(local_path)
    return key


def put_output(local_path: str) -> str:
    """Final result files: keep the original name locally, upload to s3 otherwise."""
    if BACKEND != "s3":
        return os.path.basename(local_path)
    key = f"outputs/{os.path.basename(local_path)}"
    _client().upload_file(local_path, BUCKET, key)
    os.remove(local_path)
    return key


def fetch(key: str, dest_dir: str = UPLOAD_DIR) -> str:
    """Make a stored file available as a local path for the worker."""
    if BACKEND != "s3":
        return key
    path = os.path.join(dest_dir, f"{uuid.uuid4().hex}{os.path.splitext(key)[1]}")
    _client().download_file(BUCKET, key, path)
    return path


def delete_local(path: str | None):
    if path and os.path.isfile(path):
        os.remove(path)


def presigned_url(key: str, download_name: str | None = None) -> str:
    params = {"Bucket": BUCKET, "Key": key}
    if download_name:
        params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
    return _client().generate_presigned_url("get_object", Params=params, ExpiresIn=SIGNED_URL_SECONDS)


def output_exists(key: str) -> bool:
    if BACKEND == "s3":
        return True  # expiry is handled by the bucket's lifecycle rule
    return os.path.isfile(os.path.join(OUTPUT_DIR, os.path.basename(key)))


RESULT_EXTENSIONS = (".mp4", ".srt")   # finished videos + subtitle files keep for "keep_result_days"; everything else for "keep_source_days"


def source_exists(key: str | None) -> bool:
    if not key:
        return False
    return True if BACKEND == "s3" else os.path.isfile(key)   # s3: expiry is the bucket's lifecycle rule


def touch(key: str | None):
    """Using a file (an edit) starts its keeping time again."""
    if BACKEND != "s3" and key and os.path.isfile(key):
        try:
            os.utime(key, None)
        except OSError:
            pass


def delete_output(key: str):
    if BACKEND == "s3":
        try:
            _client().delete_object(Bucket=BUCKET, Key=key)
        except Exception:
            pass
        return
    delete_local(os.path.join(OUTPUT_DIR, os.path.basename(key)))


def delete_source(key: str | None):
    if not key:
        return
    if BACKEND == "s3":
        try:
            _client().delete_object(Bucket=BUCKET, Key=key)
        except Exception:
            pass
        return
    delete_local(key)


def cleanup(result_days: float | None = None, source_days: float | None = None) -> int:
    """Delete local files past their keeping time (the admin sets the days in Settings; for s3 use bucket lifecycle rules by prefix).
    Finished videos + .srt: result days. Uploaded sources, logos, voice clips and work files: source days."""
    from admin import settings as runtime_settings
    result_days = runtime_settings.keep_result_days() if result_days is None else result_days
    source_days = runtime_settings.keep_source_days() if source_days is None else source_days
    now, removed = time.time(), 0
    for root in (UPLOAD_DIR, OUTPUT_DIR):
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                days = result_days if root == OUTPUT_DIR and name.lower().endswith(RESULT_EXTENSIONS) and os.path.basename(dirpath) != "clips" else source_days
                path = os.path.join(dirpath, name)
                try:
                    if os.path.getmtime(path) < now - days * 86400:
                        os.remove(path)
                        removed += 1
                except OSError:
                    pass
    return removed


_usage_cache: tuple[float, dict] = (0.0, {})


def disk_usage() -> dict:
    """Bytes on this machine by kind (cached 60 s): videos + subtitles, sources/logos, voice clips, other work files."""
    global _usage_cache
    if time.time() - _usage_cache[0] < 60 and _usage_cache[1]:
        return _usage_cache[1]
    out = {"results": 0, "sources": 0, "clips": 0, "other": 0}
    for root in (UPLOAD_DIR, OUTPUT_DIR):
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                try:
                    size = os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    continue
                if root == UPLOAD_DIR:
                    out["sources"] += size
                elif os.path.basename(dirpath) == "clips":
                    out["clips"] += size
                elif name.lower().endswith(RESULT_EXTENSIONS):
                    out["results"] += size
                else:
                    out["other"] += size
    out["total"] = sum(out.values())
    _usage_cache = (time.time(), out)
    return out


# ---------- voice clip cache (so editing one line only re-voices that line) ----------

def clip_path(name: str) -> str:
    d = os.path.join(OUTPUT_DIR, "clips")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def put_clip(local_path: str, name: str):
    """Keep a copy of a voice clip under `name` (copied, the local file stays)."""
    if BACKEND == "s3":
        _client().upload_file(local_path, BUCKET, f"clips/{name}")
    else:
        import shutil
        shutil.copyfile(local_path, clip_path(name))


def fetch_clip(name: str, dest: str) -> bool:
    """Copy a cached clip to `dest`; False if there is none."""
    try:
        if BACKEND == "s3":
            _client().download_file(BUCKET, f"clips/{name}", dest)
            return True
        src = clip_path(name)
        if not os.path.isfile(src):
            return False
        import shutil
        shutil.copyfile(src, dest)
        os.utime(src, None)   # reused: keep it longer
        return True
    except Exception:
        return False
