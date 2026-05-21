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
    bucket.blob(blob_name).upload_from_filename(str(local_path))


def blob_exists(blob_name: str) -> bool:
    return get_bucket().blob(blob_name).exists()
