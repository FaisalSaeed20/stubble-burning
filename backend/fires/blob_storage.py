# fires/blob_storage.py
"""Shared object-storage access for tile persistence (Backblaze B2, S3-compatible API).

Used both by request-handling views (presigned read URLs) and by the
stage-tiling pipeline, which runs its tile writes inside separate
ProcessPoolExecutor worker processes -- each worker gets its own lazily
built client via _get_client(), since a boto3 client can't be shared
across the process boundary.
"""
from django.conf import settings
import boto3

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=settings.B2_ENDPOINT_URL,
            aws_access_key_id=settings.B2_KEY_ID,
            aws_secret_access_key=settings.B2_APPLICATION_KEY,
            region_name=settings.B2_REGION,
        )
    return _client


def upload_png(blob_path, data):
    _get_client().put_object(
        Bucket=settings.B2_BUCKET_NAME,
        Key=blob_path,
        Body=data,
        ContentType="image/png",
    )


def signed_tile_url(blob_path, expiration_minutes=10):
    return _get_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.B2_BUCKET_NAME, "Key": blob_path},
        ExpiresIn=expiration_minutes * 60,
    )
