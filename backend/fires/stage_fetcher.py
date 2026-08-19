import ee
import os
import time
import datetime
import shutil
import rasterio
import mercantile
import traceback
import concurrent.futures

# --- Django Integration ---
from django.conf import settings

# --- Shared GEE helpers ---
from .gee_assets.common import get_punjab_aoi, poll_task
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
from rasterio.merge import merge

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
ZOOM_LEVELS = range(6, 14)
CPU_CORES = os.cpu_count() or 1
MAX_WORKERS = max(1, CPU_CORES // 2)

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
    mosaic, out_trans = merge(sources_to_merge)
    out_meta = sources_to_merge[0].meta.copy()
    out_meta.update({"driver": "GTiff", "height": mosaic.shape[1], "width": mosaic.shape[2], "transform": out_trans, "crs": sources_to_merge[0].crs, "compress": "lzw"})
    with rasterio.open(output_file, "w", **out_meta) as dest:
        dest.write(mosaic)
    for src in sources_to_merge:
        src.close()
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
    with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
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

        print("Defining area of interest and loading assets...")
        area_of_interest = get_punjab_aoi()

        training_table = ee.FeatureCollection(settings.GEE_DSS_TRAINING_TABLE_ASSET_ID)
        rice_map = ee.Image(settings.GEE_RICE_MASK_ASSET_ID)
        rice_mask = rice_map.eq(1)
        BANDS = ['NDVI', 'NDWI', 'VH', 'VV', 'VH_VV_ratio', 'day_of_year', 'days_since_season_start']
        LABEL = 'DSS'

        print("Training Random Forest classifier...")
        training_data = training_table.filter(ee.Filter.notNull(BANDS + [LABEL])).select(BANDS + [LABEL])
        classifier_params = {'numberOfTrees': 150, 'minLeafPopulation': 10, 'maxNodes': 128, 'bagFraction': 0.5, 'seed': 42}
        classifier = ee.Classifier.smileRandomForest(**classifier_params).train(features=training_data, classProperty=LABEL, inputProperties=BANDS)
        print("Classifier trained successfully.")

        print(f"Generating stage map for {target_date_str_gee}...")
        stage_map_to_export = generate_stage_map(target_date_str_gee, classifier, area_of_interest, rice_mask, prediction_year)

        dominant_stage = None
        stage_pixel_counts = None
        try:
            print("Computing stage pixel-count histogram...")
            # A direct .getInfo() here worked fine over the old Hafizabad-only
            # AOI, but times out ("Computation timed out") over a province-
            # wide area -- GEE's interactive-compute cluster has a time limit
            # that a full-Punjab reduceRegion blows through. Route it through
            # the batch cluster instead (async export + poll), same fix as
            # build_rice_mask.compute_rice_area_hectares.
            histogram_number = stage_map_to_export.reduceRegion(
                reducer=ee.Reducer.frequencyHistogram(),
                geometry=area_of_interest.geometry(),
                scale=10,
                maxPixels=1e13,
                bestEffort=True,
            ).get('stage')
            # Export.table.toAsset rejects features with null geometry -- the
            # geometry itself is meaningless here, only the property value matters.
            result_fc = ee.FeatureCollection(
                [ee.Feature(ee.Geometry.Point([0, 0]), {'histogram': histogram_number})]
            )
            scratch_asset_id = f'projects/{GEE_PROJECT_ID}/assets/_scratch_stage_histogram'
            try:
                ee.data.deleteAsset(scratch_asset_id)
            except ee.EEException:
                pass
            hist_task = ee.batch.Export.table.toAsset(
                collection=result_fc, description='stage_histogram_scratch', assetId=scratch_asset_id
            )
            poll_task(hist_task, label='compute stage histogram (batch)')
            histogram = ee.FeatureCollection(scratch_asset_id).first().get('histogram').getInfo()
            try:
                ee.data.deleteAsset(scratch_asset_id)
            except ee.EEException:
                pass
            if histogram:
                stage_pixel_counts = {int(k): v for k, v in histogram.items()}
                dominant_stage = max(stage_pixel_counts, key=stage_pixel_counts.get)
                print(f"  Dominant stage: {dominant_stage} (counts: {stage_pixel_counts})")
        except Exception as hist_err:
            print(f"⚠️ Could not compute stage histogram: {hist_err}")

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
                timeout=60,
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