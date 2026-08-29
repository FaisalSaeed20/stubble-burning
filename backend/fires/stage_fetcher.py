import ee
import os
import time
import datetime
import shutil
import rasterio
from rasterio.enums import Resampling
import mercantile
import traceback
import concurrent.futures

# --- Django Integration ---
from django.conf import settings

# --- Shared GEE helpers ---
from .gee_assets.common import get_punjab_aoi, get_rice_mask_image
from .blob_storage import upload_png
# Note: StageTileDate (a Django model) is deliberately NOT imported at module
# level. This module is re-imported fresh inside each ProcessPoolExecutor
# worker subprocess (spawned, not forked, on macOS/Windows), which never
# runs django.setup() -- a module-level Django model import there crashes
# every worker with AppRegistryNotReady. It's imported lazily instead, inside
# the two functions below that actually run in the main process.

# --- Google API Imports ---
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request, AuthorizedSession

# --- Tiling Imports ---
from rio_tiler.io import Reader
from rio_tiler.models import ImageData

# =================================================================================
# ⭐️ Section 1: Configuration & Setup
# =================================================================================

# --- Google Cloud & GEE Settings ---
GEE_PROJECT_ID = settings.GEE_PROJECT_ID
SCOPES = ['https://www.googleapis.com/auth/earthengine', 'https://www.googleapis.com/auth/drive']
TOKEN_PATH = settings.GEE_OAUTH_TOKEN_PATH
CREDENTIALS_PATH = settings.GEE_OAUTH_CREDENTIALS_PATH

# --- File & Directory Settings ---
GDRIVE_EXPORT_FOLDER = settings.GEE_DRIVE_EXPORT_FOLDER
TEMP_DIR = os.path.join(settings.BASE_DIR, 'temp_downloads')
MERGED_DIR = os.path.join(settings.BASE_DIR, 'merged_geotiffs')
FINAL_TILES_GCS_PREFIX = settings.B2_STAGE_TILES_PREFIX

# --- Tiling Configuration ---
# Zoom 12-13 (~1200m/~600m per tile) is close to street-level detail --
# for a province-wide crop-stage overlay that's far more resolution than
# useful, while accounting for most of the total tile count (each zoom
# level roughly quadruples the tiles of the one before it). Capping at 11
# cuts total tiles/runtime by roughly an order of magnitude for every run,
# not just this one.
ZOOM_LEVELS = range(6, 12)
CPU_CORES = os.cpu_count() or 1
# Each tile task is mostly waiting on network I/O (the B2 upload), not CPU --
# a province-wide job at zoom 6-13 is hundreds of thousands of small tiles,
# so capping workers at CPU_CORES // 2 (1 worker on a typical 2-vCPU free
# Colab/cloud runtime) serializes nearly the whole job and turns it into a
# many-hour run. Oversubscribing well past the CPU count is standard for
# I/O-bound work like this.
MAX_WORKERS = max(8, CPU_CORES)

# --- Color Map for Tiling ---
COLOR_MAP = {
    1: (0, 0, 128, 255),
    2: (0, 255, 128, 255),
    3: (255, 255, 0, 255),
    4: (255, 128, 0, 255),
    5: (139, 69, 19, 255),
}

# =================================================================================
# ⭐️ Section 2: Helper & Tiling Functions
# =================================================================================
# (These functions remain unchanged)

def _get_user_credentials():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        # On Cloud Run, TOKEN_PATH is a read-only Secret Manager mount, so
        # persisting a refreshed token can fail -- the in-memory creds are
        # still valid for this process's lifetime regardless.
        try:
            with open(TOKEN_PATH, 'w') as token:
                token.write(creds.to_json())
        except OSError as e:
            print(f"Could not persist refreshed GEE token to {TOKEN_PATH}: {e}")
    return creds

def prep_s2(image):
    scl = image.select('SCL')
    good_pixels = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(7))
    ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
    ndwi = image.normalizedDifference(['B3', 'B8']).rename('NDWI')
    return image.addBands([ndvi, ndwi]).updateMask(good_pixels) \
        .select(['NDVI', 'NDWI']).copyProperties(image, ["system:time_start"])

def prep_s1(image):
    smoothed = image.focal_median(**{'radius': 50, 'units': 'meters'})
    vh_vv_ratio = image.select('VH').divide(image.select('VV')).rename('VH_VV_ratio')
    return smoothed.select(['VH', 'VV']).addBands(vh_vv_ratio) \
        .copyProperties(image, ['system:time_start'])

def generate_stage_map(map_date, classifier, area_of_interest, rice_mask, prediction_year):
    date = ee.Date(map_date)
    date_range = ee.DateRange(date.advance(-5, 'day'), date.advance(5, 'day'))
    s2_image = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterDate(date_range).filterBounds(area_of_interest).map(prep_s2).median()
    s1_image = ee.ImageCollection('COPERNICUS/S1_GRD').filter(ee.Filter.eq('instrumentMode', 'IW')).filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH')).filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV')).filterDate(date_range).filterBounds(area_of_interest).map(prep_s1).median()
    season_start = ee.Date(f'{prediction_year}-05-15')
    day_of_year = ee.Image.constant(date.getRelative('day', 'year')).rename('day_of_year')
    days_since_season_start = ee.Image.constant(date.difference(season_start, 'day')).rename('days_since_season_start')
    input_image = ee.Image.cat([s2_image, s1_image, day_of_year, days_since_season_start])
    dss_map = input_image.classify(classifier).rename('DSS')
    stage_map = dss_map.expression(
        "(b(0) > 120) ? 5" + ": (b(0) > 80) ? 4" + ": (b(0) > 55) ? 3" + ": (b(0) > 15) ? 2" + ": 1"
    ).rename('stage')
    return stage_map.updateMask(rice_mask).rename('stage').byte()

def build_classifier_and_stage_map(target_date_str_gee, prediction_year):
    """Rebuilds the trained classifier + stage-map ee.Image graph for a given
    date. Cheap to call repeatedly (lazy graph construction; the only real
    compute is classifier.train(), which is fast) -- shared between the main
    pipeline and the CI recovery script (scripts/ci_tile_from_scratch.py) so
    a stuck/OOM-killed run can be resumed without re-deriving this by hand."""
    area_of_interest = get_punjab_aoi()
    training_table = ee.FeatureCollection(settings.GEE_DSS_TRAINING_TABLE_ASSET_ID)
    rice_map = get_rice_mask_image(settings.GEE_RICE_MASK_ASSET_ID)
    rice_mask = rice_map.eq(1)
    BANDS = ['NDVI', 'NDWI', 'VH', 'VV', 'VH_VV_ratio', 'day_of_year', 'days_since_season_start']
    LABEL = 'DSS'

    training_data = training_table.filter(ee.Filter.notNull(BANDS + [LABEL])).select(BANDS + [LABEL])
    classifier_params = {'numberOfTrees': 150, 'minLeafPopulation': 10, 'maxNodes': 128, 'bagFraction': 0.5, 'seed': 42}
    classifier = ee.Classifier.smileRandomForest(**classifier_params).train(features=training_data, classProperty=LABEL, inputProperties=BANDS)
    stage_map_to_export = generate_stage_map(target_date_str_gee, classifier, area_of_interest, rice_mask, prediction_year)
    return area_of_interest, stage_map_to_export


def compute_stage_histogram(stage_map_to_export, area_of_interest):
    """Returns (dominant_stage, stage_pixel_counts) or (None, None) on
    failure. Computed per-district and summed client-side rather than one
    province-wide reduceRegion -- even routed through an async batch export
    (the original fix for GEE's interactive-compute time limit), a single
    province-wide reduceRegion reliably stalled in READY for hours with zero
    progress on GEE's free-tier batch queue. Each per-district reduceRegion
    is much closer in size to the original Hafizabad-pilot AOI, which always
    completed quickly -- same class of fix as
    build_rice_mask.export_rice_mask_by_district."""
    from .gee_assets.common import district_asset_slug, get_punjab_district_names, poll_tasks

    try:
        print("Computing stage pixel-count histogram (per district)...")
        district_names = get_punjab_district_names()

        tasks_by_label = {}
        asset_ids = {}
        for name in district_names:
            slug = district_asset_slug(name)
            asset_id = f'projects/{GEE_PROJECT_ID}/assets/_scratch_stage_histogram_{slug}'
            asset_ids[name] = asset_id
            district_geom = area_of_interest.filter(ee.Filter.eq('ADM2_NAME', name)).geometry()
            histogram_dict = ee.Dictionary(stage_map_to_export.reduceRegion(
                reducer=ee.Reducer.frequencyHistogram(),
                geometry=district_geom,
                scale=10,
                maxPixels=1e13,
                bestEffort=True,
            ).get('stage'))
            # Export.table.toAsset can't encode a Dictionary as a feature
            # property (only simple types like numbers/strings) -- unpack
            # into one property per stage instead, since stages are always
            # a fixed 1-5 (see generate_stage_map's classification above).
            # Export.table.toAsset also rejects features with null geometry;
            # the geometry itself is meaningless here, only the properties matter.
            props = {f'stage_{i}': histogram_dict.get(ee.String(str(i)), 0) for i in range(1, 6)}
            result_fc = ee.FeatureCollection([ee.Feature(ee.Geometry.Point([0, 0]), props)])
            try:
                ee.data.deleteAsset(asset_id)
            except ee.EEException:
                pass
            tasks_by_label[name] = ee.batch.Export.table.toAsset(
                collection=result_fc, description=f'stage_histogram_{slug}', assetId=asset_id
            )

        results = poll_tasks(tasks_by_label)
        failed = {name: status for name, status in results.items() if status['state'] != 'COMPLETED'}
        if failed:
            print(f"⚠️ {len(failed)} district histogram task(s) did not complete: {list(failed.keys())}")

        histogram = {i: 0 for i in range(1, 6)}
        for name, status in results.items():
            if status['state'] != 'COMPLETED':
                continue
            asset_id = asset_ids[name]
            row = ee.FeatureCollection(asset_id).first().toDictionary().getInfo()
            for key, value in row.items():
                if key.startswith('stage_') and value:
                    histogram[int(key.split('_')[1])] += value
            try:
                ee.data.deleteAsset(asset_id)
            except ee.EEException:
                pass

        histogram = {stage: count for stage, count in histogram.items() if count}
        if histogram:
            dominant_stage = max(histogram, key=histogram.get)
            print(f"  Dominant stage: {dominant_stage} (counts: {histogram})")
            return dominant_stage, histogram
        return None, None
    except Exception as hist_err:
        print(f"⚠️ Could not compute stage histogram: {hist_err}")
        return None, None


def merge_geotiffs_in_directory(input_dir, output_dir, date_str):
    os.makedirs(output_dir, exist_ok=True)
    tiff_parts = [os.path.join(input_dir, f) for f in os.listdir(input_dir) if f.endswith('.tif')]
    if not tiff_parts:
        raise Exception("No .tif files found in the directory to merge.")
    if len(tiff_parts) == 1:
        merged_file_path = os.path.join(output_dir, f"Punjab_Stages_Merged_{date_str}.tif")
        shutil.move(tiff_parts[0], merged_file_path)
        return merged_file_path
    output_file = os.path.join(output_dir, f"Punjab_Stages_Merged_{date_str}.tif")
    print(f"Merging {len(tiff_parts)} GeoTIFF parts into '{output_file}'...")
    sources_to_merge = [rasterio.open(fp) for fp in tiff_parts]

    # rasterio.merge.merge() loads every source array AND the full combined
    # mosaic array into memory at once -- for a province-scale raster that
    # reliably OOM-crashes even a 12GB Colab runtime (the crash is silent
    # from this script's point of view; the notebook just gets killed and
    # restarted mid-cell). Parts here are known to be a non-overlapping grid
    # (GEE's own export tiling), so each one can be written straight into its
    # destination window on disk instead -- only one source array is ever
    # in memory at a time.
    res_x, res_y = sources_to_merge[0].res
    left = min(src.bounds.left for src in sources_to_merge)
    bottom = min(src.bounds.bottom for src in sources_to_merge)
    right = max(src.bounds.right for src in sources_to_merge)
    top = max(src.bounds.top for src in sources_to_merge)
    width = round((right - left) / res_x)
    height = round((top - bottom) / res_y)
    out_transform = rasterio.transform.from_origin(left, top, res_x, res_y)

    out_meta = sources_to_merge[0].meta.copy()
    out_meta.update({
        "driver": "GTiff", "height": height, "width": width,
        "transform": out_transform, "crs": sources_to_merge[0].crs, "compress": "lzw",
        # Without internal tiling, GDAL writes one full-width strip per row --
        # reading a single 256x256 output tile from a province-scale raster
        # then forces a read of the entire row width for every row touched.
        # With 4 parallel workers all doing that against a multi-GB raster on
        # an 8GB machine, this reliably OOM-kills a worker
        # (BrokenProcessPool) partway through tiling. Internal 256x256
        # blocks make each worker's read proportional to the output tile
        # size instead of the raster's full width.
        "tiled": True, "blockxsize": 256, "blockysize": 256,
    })
    with rasterio.open(output_file, "w", **out_meta) as dest:
        for src in sources_to_merge:
            col_off = round((src.bounds.left - left) / res_x)
            row_off = round((top - src.bounds.top) / res_y)
            window = rasterio.windows.Window(col_off, row_off, src.width, src.height)
            dest.write(src.read(), window=window)
            src.close()
        # Without overviews, every tile read at low zoom still decodes from
        # the full-resolution data -- rio-tiler warns on this per read (once
        # per tile, i.e. hundreds of thousands of times over a tiling run)
        # and is measurably slower doing it. Building them once here instead
        # costs a few seconds and removes both problems.
        dest.build_overviews([2, 4, 8, 16, 32], Resampling.nearest)
    print(f"✅ Successfully created merged file: {output_file}")
    return output_file

def _process_tile_worker(args):
    input_geotiff, tile, gcs_prefix, date_str = args
    try:
        with Reader(input_geotiff) as reader:
            img_data, mask = reader.tile(tile.x, tile.y, tile.z, tilesize=256, resampling_method="nearest")
        if not img_data.any():
            return "skipped"
        png_data = ImageData(img_data, mask).render(img_format="PNG", colormap=COLOR_MAP)
        if settings.B2_BUCKET_NAME:
            blob_path = f"{gcs_prefix}/{tile.z}/{tile.x}/{tile.y}.png"
            upload_png(blob_path, png_data)
        else:
            # Local dev fallback: no bucket configured, write straight to
            # disk (matches views.py's read-side fallback for the same case).
            tile_dir = os.path.join(settings.BASE_DIR, "static", "stage_tiles", date_str, str(tile.z), str(tile.x))
            os.makedirs(tile_dir, exist_ok=True)
            with open(os.path.join(tile_dir, f"{tile.y}.png"), "wb") as f:
                f.write(png_data)
        return "success"
    except Exception:
        return f"failed: Tile {tile}\n{traceback.format_exc()}"

def generate_tiles_for_file(geotiff_path, date_str):
    from .models import StageTileDate

    gcs_prefix = f"{FINAL_TILES_GCS_PREFIX}/{date_str}"
    if StageTileDate.objects.filter(date_str=date_str).exists():
        print(f"Skipping tiling for '{date_str}': StageTileDate record already exists.")
        return
    print(f"--- Processing tiles for date: {date_str} ---")
    all_tiles_to_process = []
    with rasterio.open(geotiff_path) as src:
        bounds = src.bounds
        for zoom in ZOOM_LEVELS:
            all_tiles_to_process.extend(mercantile.tiles(*bounds, zooms=[zoom]))
    tasks = [(geotiff_path, tile, gcs_prefix, date_str) for tile in all_tiles_to_process]
    print(f"Generating {len(tasks)} tiles using {MAX_WORKERS} workers...")
    # max_tasks_per_child periodically recycles each worker process instead of
    # keeping the same one alive for the whole run -- a province-wide job at
    # zoom 6-13 opens the merged raster hundreds of thousands of times across
    # a run lasting over an hour, and any small per-open leak in GDAL's/
    # rio-tiler's internal caching compounds over that many repeated opens in
    # a single long-lived process until it OOM-crashes the whole runtime late
    # in the run (observed: died mid-zoom-13 after ~1h of otherwise-successful
    # uploads). Recycling bounds how much any such leak can accumulate.
    with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS, max_tasks_per_child=1000) as executor:
        results = list(executor.map(_process_tile_worker, tasks))
    success_count = results.count("success")
    skipped_count = results.count("skipped")
    failed_count = len([r for r in results if r not in ["success", "skipped"]])
    print(f"✨ Tiling Done. Success: {success_count}, Skipped (empty): {skipped_count}, Failed: {failed_count}")
    if failed_count == 0:
        StageTileDate.objects.get_or_create(date_str=date_str)


# =================================================================================
# ⭐️ Section 3: Main Execution Function
# =================================================================================

def fetch_and_process_latest_stage_map():
    """Main function to run the entire data fetching and processing pipeline."""
    from .models import StageTileDate

    try:
        print("Authenticating as user for GEE and Google Drive...")
        creds = _get_user_credentials()
        ee.Initialize(project=GEE_PROJECT_ID, credentials=creds)
        # The googleapiclient/httplib2 stack was repeatedly hanging/timing out
        # on the Drive file-search and download calls specifically (while GEE
        # calls over the same network succeeded fine for many minutes) --
        # traced to a stuck IPv6 connection attempt. requests/urllib3 (via
        # AuthorizedSession, same as the rest of this network-facing code)
        # doesn't have that problem, so Drive access goes through that
        # instead of googleapiclient's own HTTP stack.
        drive_session = AuthorizedSession(creds)
        print("✅ GEE authentication successful.")

        target_date = datetime.date.today() - datetime.timedelta(days=2)
        target_date_str_gee = target_date.strftime('%Y-%m-%d')
        target_date_str_file = target_date.strftime('%Y%m%d')
        prediction_year = str(target_date.year)
        
        print(f"\n[{datetime.datetime.utcnow()}] Running Stage Map job for date: {target_date_str_gee}")

        if StageTileDate.objects.filter(date_str=target_date_str_file).exists():
            print(f"👍 Stage tiles for {target_date_str_file} already exist. Skipping job.")
            return

        print("Defining area of interest and loading assets, training classifier...")
        area_of_interest, stage_map_to_export = build_classifier_and_stage_map(target_date_str_gee, prediction_year)
        print("Classifier trained, stage map graph built.")

        dominant_stage, stage_pixel_counts = compute_stage_histogram(stage_map_to_export, area_of_interest)

        export_filename = f'Punjab_Stages_{target_date_str_file}'
        print(f"Starting GEE export task: '{export_filename}'...")
        task = ee.batch.Export.image.toDrive(
            image=stage_map_to_export, 
            description=export_filename, 
            folder=GDRIVE_EXPORT_FOLDER,
            region=area_of_interest.geometry(),
            # --- UPDATED LINE: Higher resolution for smaller area ---
            scale=10, 
            maxPixels=1e13, 
            crs='EPSG:4326'
        )
        task.start()

        while task.active():
            status = task.status()
            start_ms = status.get('start_timestamp_ms') or 0
            elapsed_time = int(time.time() - start_ms / 1000) if start_ms else 0
            print(f"  Polling task: {status['state']} (elapsed: {elapsed_time}s)")
            time.sleep(60)
        
        if task.status()['state'] != 'COMPLETED':
            raise Exception(f"GEE task failed: {task.status().get('error_message', 'No error message available.')}")
        
        print(f"\n✅ GEE export task '{export_filename}' completed.")
        
        print("Searching for exported file(s) in Google Drive...")
        os.makedirs(TEMP_DIR, exist_ok=True)
        q_filter = f"name contains '{export_filename}' and mimeType='image/tiff'"
        list_resp = drive_session.get(
            'https://www.googleapis.com/drive/v3/files',
            params={'q': q_filter, 'spaces': 'drive', 'fields': 'files(id, name)'},
            timeout=60,
        )
        list_resp.raise_for_status()
        files_to_download = list_resp.json().get('files', [])

        if not files_to_download:
            raise Exception(f"Could not find exported files for '{export_filename}' in Drive folder '{GDRIVE_EXPORT_FOLDER}'.")

        print(f"Found {len(files_to_download)} file part(s). Starting download...")
        for file_part in files_to_download:
            file_id, file_name = file_part.get('id'), file_part.get('name')
            local_path = os.path.join(TEMP_DIR, file_name)
            with drive_session.get(
                f'https://www.googleapis.com/drive/v3/files/{file_id}',
                params={'alt': 'media'},
                stream=True,
                # Province-scale export file parts are much larger than the
                # Hafizabad-only pilot's -- a 60s read timeout was too tight
                # and killed a download partway through on a large part,
                # losing already-downloaded parts too (cleanup ran on any
                # exception). 300s gives large chunks enough room on a slow
                # connection without waiting forever on a genuinely dead one.
                timeout=300,
            ) as file_resp:
                file_resp.raise_for_status()
                with open(local_path, "wb") as f:
                    for chunk in file_resp.iter_content(chunk_size=8 * 1024 * 1024):
                        f.write(chunk)
            print(f"  Downloaded '{file_name}'.")
        
        print("✅ Download complete.")

        # The GEE export + Drive download above can take 20+ minutes with zero
        # DB activity. Managed Postgres providers (e.g. Neon's pooled endpoint)
        # silently drop idle connections well within that window, and this is
        # a single long-lived process rather than a series of web requests, so
        # Django's normal CONN_MAX_AGE-based recycling (tied to the
        # request_finished signal) never gets a chance to kick in. Force a
        # fresh connection before the first DB write after the idle gap.
        from django.db import connection
        connection.close()

        merged_geotiff_path = merge_geotiffs_in_directory(TEMP_DIR, MERGED_DIR, target_date_str_file)
        generate_tiles_for_file(merged_geotiff_path, target_date_str_file)

        if dominant_stage is not None:
            StageTileDate.objects.filter(date_str=target_date_str_file).update(
                dominant_stage=dominant_stage, stage_pixel_counts=stage_pixel_counts
            )

        print(f"\n🎉 Successfully completed full pipeline for {target_date_str_file}.")

    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")
        
    finally:
        print("Cleaning up temporary directories...")
        if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
        if os.path.exists(MERGED_DIR): shutil.rmtree(MERGED_DIR)
        print("Cleanup complete.")