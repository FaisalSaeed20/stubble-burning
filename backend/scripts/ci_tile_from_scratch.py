"""
Finishes a crop-stage pipeline run from already-exported raw GeoTIFF parts
sitting in a B2 scratch prefix, instead of running the memory-heavy
merge+tile step on a local machine. Also computes the dominant_stage/
pixel-histogram itself via Earth Engine (service account auth) -- no
manually-typed values needed.

Why this exists: merging+tiling a province-scale raster (multi-GB) with
several parallel workers reliably exhausts RAM on an 8GB laptop (a fixed
bug in merge_geotiffs_in_directory's output layout made this worse, but
even with that fixed, a laptop also running a browser/IDE/etc. has much
less headroom than a dedicated CI runner). This script re-does the
histogram/download-from-scratch/merge/tile/DB-write steps, meant to run in
GitHub Actions (or any machine with several GB of free RAM) instead.

Usage: set the env vars below, then run
    python backend/scripts/ci_tile_from_scratch.py <date_str>
e.g.
    python backend/scripts/ci_tile_from_scratch.py 20260823
"""
import datetime
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

import boto3
from django.conf import settings

from fires.gee_assets.common import init_ee
from fires.stage_fetcher import (
    TEMP_DIR,
    MERGED_DIR,
    build_classifier_and_stage_map,
    compute_stage_histogram,
    merge_geotiffs_in_directory,
    generate_tiles_for_file,
)
from fires.models import StageTileDate


def main():
    date_str = sys.argv[1]
    target_date_str_gee = datetime.datetime.strptime(date_str, '%Y%m%d').strftime('%Y-%m-%d')
    prediction_year = date_str[:4]

    scratch_prefix = f'scratch/punjab_stages_{date_str}/'
    os.makedirs(TEMP_DIR, exist_ok=True)

    print("Authenticating with GEE (service account)...")
    init_ee()

    print(f"Rebuilding classifier + stage map for {target_date_str_gee} (cheap, lazy graph)...")
    area_of_interest, stage_map_to_export = build_classifier_and_stage_map(target_date_str_gee, prediction_year)

    dominant_stage, stage_pixel_counts = compute_stage_histogram(stage_map_to_export, area_of_interest)

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
            dominant_stage=dominant_stage, stage_pixel_counts=stage_pixel_counts
        )
        print(f"Updated StageTileDate({date_str}) with dominant_stage={dominant_stage}")

    print("Cleaning up scratch files on B2 ...")
    for key in keys:
        s3.delete_object(Bucket=settings.B2_BUCKET_NAME, Key=key)

    print(f"Done: {date_str}")


if __name__ == '__main__':
    main()
