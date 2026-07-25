# fires/gcs_utils.py
"""Shared GCS access for tile storage.

Used both by request-handling views (signed read URLs) and by the
stage-tiling pipeline, which runs its tile writes inside separate
ProcessPoolExecutor worker processes -- each worker gets its own lazily
built client via _get_client(), since a storage.Client() can't be shared
across the process boundary.
"""
from datetime import timedelta

from django.conf import settings
from google.cloud import storage

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = storage.Client()
    return _client


def get_bucket():
    return _get_client().bucket(settings.GCS_BUCKET_NAME)


def upload_png(blob_path, data):
    get_bucket().blob(blob_path).upload_from_string(data, content_type="image/png")


def signed_tile_url(blob_path, expiration_minutes=10):
    blob = get_bucket().blob(blob_path)
    return blob.generate_signed_url(
        version="v4", expiration=timedelta(minutes=expiration_minutes), method="GET"
    )
