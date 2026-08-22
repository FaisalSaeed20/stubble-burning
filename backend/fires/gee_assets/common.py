"""Shared Earth Engine helpers: one canonical AOI, auth, and task polling.

gee_fetcher.py and stage_fetcher.py used to each define their own version of
the AOI boundary (level1 vs level2 GAUL filters) -- consolidated here so the
rice mask and DSS training table line up with whatever the fetchers actually
mask against at runtime.
"""
import time

import ee
from django.conf import settings


def get_punjab_aoi():
    """Province-wide AOI (all of Punjab, Pakistan). Was Hafizabad District
    only (a single ADM2_NAME) until the pilot scope was expanded."""
    return ee.FeatureCollection('FAO/GAUL/2015/level2').filter(
        ee.Filter.And(
            ee.Filter.eq('ADM0_NAME', 'Pakistan'),
            ee.Filter.eq('ADM1_NAME', 'Punjab'),
        )
    )


def init_ee():
    credentials = ee.ServiceAccountCredentials(
        settings.GEE_SERVICE_ACCOUNT_EMAIL, settings.GEE_KEY_FILE_PATH
    )
    ee.Initialize(project=settings.GEE_PROJECT_ID, credentials=credentials)


def poll_task(task, label, poll_seconds=30):
    task.start()
    print(f"Started export task '{label}' ({task.id})...")
    while task.active():
        print(f"  ...task '{label}' still running ({task.status()['state']})")
        time.sleep(poll_seconds)
    status = task.status()
    if status['state'] != 'COMPLETED':
        raise RuntimeError(f"Task '{label}' finished with state {status['state']}: {status.get('error_message')}")
    print(f"Task '{label}' completed.")
    return status


def poll_tasks(tasks_by_label, poll_seconds=30):
    """Starts and polls several tasks concurrently instead of one at a time.

    A single province-wide export can end up competing for one large worker
    slot on GEE's free-tier batch queue and stall for a very long time with
    no visible progress; splitting the same total work into several smaller
    tasks (e.g. one per district) and running them concurrently gets each
    individual task queued independently, so the wall-clock cost is closer to
    one shard's export time than N times it.

    Returns {label: status} for every task, including failures -- callers
    decide how to handle partial failure rather than this raising on the
    first one, since with many shards some failing shouldn't necessarily
    abort the rest.
    """
    pending = {}
    for label, task in tasks_by_label.items():
        task.start()
        print(f"Started export task '{label}' ({task.id})...")
        pending[label] = task

    results = {}
    while pending:
        time.sleep(poll_seconds)
        for label in list(pending):
            status = pending[label].status()
            if status['state'] in ('COMPLETED', 'FAILED', 'CANCELLED'):
                results[label] = status
                if status['state'] == 'COMPLETED':
                    print(f"'{label}' completed.")
                else:
                    print(f"'{label}' finished with state {status['state']}: {status.get('error_message')}")
                del pending[label]
        if pending:
            print(f"  ...{len(pending)} export(s) still running: {sorted(pending.keys())}")
    return results


def get_punjab_district_names():
    """District names (ADM2_NAME) for all of Punjab, from the same GAUL
    source as get_punjab_aoi() -- used to shard province-wide exports into
    one task per district."""
    return get_punjab_aoi().aggregate_array('ADM2_NAME').getInfo()


def district_asset_slug(district_name):
    return district_name.lower().replace(' ', '_').replace('.', '')


def get_district_asset_mosaic(base_asset_id, district_names):
    """Builds one logical ee.Image by mosaicking per-district assets that
    were exported under '{base_asset_id}_{slug}' naming (see
    build_rice_mask.export_rice_mask_by_district) -- a drop-in replacement
    for ee.Image(base_asset_id) wherever a single province-wide asset would
    otherwise be read."""
    images = [ee.Image(f'{base_asset_id}_{district_asset_slug(name)}') for name in district_names]
    return ee.ImageCollection(images).mosaic()


def get_rice_mask_image(base_asset_id):
    """Reads the rice mask regardless of whether it was exported as one
    province-wide asset (export_rice_mask) or as one asset per district
    (export_rice_mask_by_district) -- callers (gee_fetcher, stage_fetcher,
    build_dss_training_table) don't need to know which export path was used."""
    try:
        ee.data.getAsset(base_asset_id)
        return ee.Image(base_asset_id)
    except ee.EEException:
        return get_district_asset_mosaic(base_asset_id, get_punjab_district_names())
