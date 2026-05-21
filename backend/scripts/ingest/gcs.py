from __future__ import annotations

import os
from pathlib import Path

from google.cloud import storage


def get_bucket() -> storage.Bucket:
    return storage.Client().bucket(os.environ["GCS_BUCKET"])


def download_to_file(blob_name: str, local_path: Path) -> bool:
    """Download blob to local_path. Returns False if blob doesn't exist."""
    bucket = get_bucket()
    blob = bucket.blob(blob_name)
    if not blob.exists():
        return False
    blob.download_to_filename(str(local_path))
    return True


def upload_from_file(local_path: Path, blob_name: str) -> None:
    bucket = get_bucket()
    blob = bucket.blob(blob_name)
    size = local_path.stat().st_size
    # Use resumable upload for files over 5 MB so timeouts don't abort mid-transfer.
    if size > 5 * 1024 * 1024:
        with open(local_path, "rb") as f:
            blob.upload_from_file(f, timeout=600, checksum="crc32c")
    else:
        blob.upload_from_filename(str(local_path), timeout=600)


def blob_exists(blob_name: str) -> bool:
    return get_bucket().blob(blob_name).exists()
