"""
Finishes a crop-stage pipeline run using a stage-histogram export that
already completed on GEE (visible as COMPLETED on the Tasks page) but whose
result was never read back, because the process that submitted it was
stopped/restarted before it got there. Skips recomputing the histogram
entirely -- just reads the existing scratch asset -- then does the same
download-from-scratch/merge/tile/DB-write steps as ci_tile_from_scratch.py.

Usage:
    python backend/scripts/finish_from_completed_histogram.py <date_str> <scratch_asset_id>
e.g.
    python backend/scripts/finish_from_completed_histogram.py 20260823 projects/gee-stubble-burning/assets/_scratch_stage_histogram
"""
import datetime
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

import boto3
import ee
from django.conf import settings

from fires.gee_assets.common import init_ee
from fires.stage_fetcher import (
    TEMP_DIR,
    MERGED_DIR,
    merge_geotiffs_in_directory,
    generate_tiles_for_file,
)
from fires.models import StageTileDate


def main():
    date_str = sys.argv[1]
    scratch_asset_id = sys.argv[2]

    scratch_prefix = f'scratch/punjab_stages_{date_str}/'
    os.makedirs(TEMP_DIR, exist_ok=True)

    print("Authenticating with GEE (service account)...")
    init_ee()

    print(f"Reading already-completed histogram from {scratch_asset_id} ...")
    row = ee.FeatureCollection(scratch_asset_id).first().toDictionary().getInfo()
    histogram = {
        int(key.split('_')[1]): value
        for key, value in row.items()
        if key.startswith('stage_') and value
    }
    dominant_stage = max(histogram, key=histogram.get) if histogram else None
    print(f"  dominant_stage={dominant_stage} histogram={histogram}")

    s3 = boto3.client(
        's3',
        endpoint_url=settings.B2_ENDPOINT_URL,
        aws_access_key_id=settings.B2_KEY_ID,
        aws_secret_access_key=settings.B2_APPLICATION_KEY,
        region_name=settings.B2_REGION,
    )

    print(f"Downloading raw parts from s3://{settings.B2_BUCKET_NAME}/{scratch_prefix} ...")
    paginator = s3.get_paginator('list_objects_v2')
    keys = []
    for page in paginator.paginate(Bucket=settings.B2_BUCKET_NAME, Prefix=scratch_prefix):
        for obj in page.get('Contents', []):
            keys.append(obj['Key'])
    if not keys:
        raise Exception(f"No files found under scratch prefix {scratch_prefix}")

    for key in keys:
        local_name = key.rsplit('/', 1)[-1]
        local_path = os.path.join(TEMP_DIR, local_name)
        print(f"  Downloading {key} -> {local_path}")
        s3.download_file(settings.B2_BUCKET_NAME, key, local_path)

    print("Merging (with internal tiling) ...")
    merged_geotiff_path = merge_geotiffs_in_directory(TEMP_DIR, MERGED_DIR, date_str)

    print("Tiling and uploading to B2 ...")
    generate_tiles_for_file(merged_geotiff_path, date_str)

    if dominant_stage is not None:
        StageTileDate.objects.filter(date_str=date_str).update(
            dominant_stage=dominant_stage, stage_pixel_counts=histogram
        )
        print(f"Updated StageTileDate({date_str}) with dominant_stage={dominant_stage}")

    print("Cleaning up scratch files on B2 ...")
    for key in keys:
        s3.delete_object(Bucket=settings.B2_BUCKET_NAME, Key=key)

    print("Cleaning up scratch GEE asset ...")
    try:
        ee.data.deleteAsset(scratch_asset_id)
    except ee.EEException:
        pass

    print(f"Done: {date_str}")


if __name__ == '__main__':
    main()
