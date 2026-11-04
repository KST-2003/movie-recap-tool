"""File storage. local: files live on this machine (single server / dev).
s3: any S3-compatible bucket (DigitalOcean Spaces, AWS S3, MinIO) so API and worker machines can be separate.
Set STORAGE_BACKEND=s3 plus S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY, S3_ENDPOINT (e.g. https://sgp1.digitaloceanspaces.com), S3_REGION."""
import os
import time
import uuid

from config import FILE_TTL_HOURS, OUTPUT_DIR, SIGNED_URL_SECONDS, UPLOAD_DIR

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


def cleanup(max_age_hours: float = FILE_TTL_HOURS) -> int:
    """Delete local uploads/outputs older than the retention window. (For s3, set a bucket lifecycle rule.)"""
    cutoff, removed = time.time() - max_age_hours * 3600, 0
    for root in (UPLOAD_DIR, OUTPUT_DIR):
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                path = os.path.join(dirpath, name)
                try:
                    if os.path.getmtime(path) < cutoff:
                        os.remove(path)
                        removed += 1
                except OSError:
                    pass
    return removed
