"""Shared Earth Engine helpers: one canonical AOI, auth, and task polling.

gee_fetcher.py and stage_fetcher.py used to each define their own version of
the Hafizabad boundary (level1 vs level2 GAUL filters) -- consolidated here
so the rice mask and DSS training table line up with whatever the fetchers
actually mask against at runtime.
"""
import time

import ee
from django.conf import settings


def get_hafizabad_aoi():
    return ee.FeatureCollection('FAO/GAUL/2015/level2').filter(
        ee.Filter.And(
            ee.Filter.eq('ADM0_NAME', 'Pakistan'),
            ee.Filter.eq('ADM1_NAME', 'Punjab'),
            ee.Filter.eq('ADM2_NAME', 'Hafizabad District'),
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
