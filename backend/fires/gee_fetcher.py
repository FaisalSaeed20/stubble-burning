# fires/gee_fetcher.py

import ee
import datetime
from django.conf import settings
from .models import FirePoint, FireObservation
from .gee_assets.common import get_punjab_aoi, get_rice_mask_image, init_ee
from django.db import transaction, IntegrityError
from django.core.exceptions import ObjectDoesNotExist

# --- GEE Authentication (runs once when the app starts) ---
try:
    init_ee()
    print("✅ GEE authentication successful.")
except Exception as e:
    print(f"❌ ERROR: GEE authentication failed: {e}")
# -------------------------------------------------------------


def fetch_and_load_new_fires(season_year=None, start_date=None, end_date=None):
    """
    Default (all args None) is the live/rolling behavior: current year's season,
    last FIRE_LOOKBACK_DAYS days of new fires.

    Pass season_year/start_date/end_date to backfill a past window instead (e.g.
    a completed burning season) -- useful for testing fire-dependent features
    when there's nothing in the rolling lookback window (off-season).
    """
    print(f"\n[{datetime.datetime.utcnow()}] Running GEE fire data fetch job...")

    try:
        # ==============================================================================
        # --- Phase 1: Configuration (Translated from JS) ---
        # ==============================================================================
        RICE_MAP_ASSET_PATH = settings.GEE_RICE_MASK_ASSET_ID
        aoi = get_punjab_aoi().geometry()
        S2_BANDS = ['NDVI', 'NDWI', 'NBR', 'NDRE']
        S1_BANDS = ['VV', 'VH']
        ALL_BANDS = S2_BANDS + S1_BANDS

        # Rice season runs roughly May-Nov; use the current year's season so a
        # run today always covers this year's transplanting through harvest,
        # unless a specific season_year was passed in for a historical backfill.
        season_year = season_year or datetime.datetime.now().year
        ANALYSIS_START_DATE = f'{season_year}-05-01'
        FIRE_SEASON_END = end_date or datetime.datetime.now().strftime('%Y-%m-%d')

        # Rolling lookback window for *new* fire detections, so each run only
        # picks up recent FIRMS hits instead of re-scanning a fixed past range --
        # unless a specific start_date/end_date range was passed in.
        if start_date and end_date:
            start_date_filter = ee.Date(start_date)
            end_date_filter = ee.Date(end_date)
        else:
            lookback_days = settings.FIRE_LOOKBACK_DAYS
            start_date_filter = ee.Date(datetime.datetime.now().strftime('%Y-%m-%d')).advance(-lookback_days, 'day')
            end_date_filter = ee.Date(datetime.datetime.now().strftime('%Y-%m-%d'))
        print(f"🔍 Searching for new fires from {start_date_filter.format().getInfo()} to {end_date_filter.format().getInfo()}")

        # ==============================================================================
        # --- Phase 2: Data Preparation & Compositing (Corrected Logic from JS) ---
        # ==============================================================================
        def prepS2(image):
            scl = image.select('SCL')
            goodPixels = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(6)).Or(scl.eq(7))
            ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
            ndre = image.normalizedDifference(['B8', 'B5']).rename('NDRE')
            ndwi = image.normalizedDifference(['B3', 'B8']).rename('NDWI')
            nbr = image.normalizedDifference(['B8', 'B12']).rename('NBR')
            return image.addBands([ndvi, ndre, ndwi, nbr]).updateMask(goodPixels).select(S2_BANDS).copyProperties(image, ['system:time_start'])

        s2Collection = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(aoi).filterDate(ANALYSIS_START_DATE, FIRE_SEASON_END).map(prepS2)

        def prepS1(image):
            vv_vh = image.select('VV', 'VH')
            smoothed = vv_vh.focal_median(35, 'circle', 'meters')
            return smoothed.rename(S1_BANDS).copyProperties(image, ['system:time_start'])

        s1Collection = ee.ImageCollection('COPERNICUS/S1_GRD').filterBounds(aoi).filterDate(ANALYSIS_START_DATE, FIRE_SEASON_END).filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV')).filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH')).filter(ee.Filter.eq('instrumentMode', 'IW')).filter(ee.Filter.eq('orbitProperties_pass', 'DESCENDING')).map(prepS1)

        def createNullBands(bandNames):
            zeros = ee.List.repeat(0, ee.List(bandNames).length())
            return ee.Image.constant(zeros).toFloat().rename(bandNames).mask(ee.Image(0))

        s2WithNulls = s2Collection.map(lambda image: image.addBands(createNullBands(S1_BANDS)).select(ALL_BANDS))
        s1WithNulls = s1Collection.map(lambda image: image.addBands(createNullBands(S2_BANDS)).select(ALL_BANDS))
        dailyMergedCollection = ee.ImageCollection(s1WithNulls.merge(s2WithNulls)).sort('system:time_start')

        COMPOSITE_INTERVAL = 5 # Days
        dateList = ee.List.sequence(ee.Date(ANALYSIS_START_DATE).millis(), ee.Date(FIRE_SEASON_END).millis(), 1000 * 60 * 60 * 24 * COMPOSITE_INTERVAL)
        emptyImageWithBands = createNullBands(ALL_BANDS)

        def create_composite(startDateMillis):
            startDate = ee.Date(startDateMillis)
            endDate = startDate.advance(COMPOSITE_INTERVAL, 'day')
            filtered = dailyMergedCollection.filterDate(startDate, endDate)
            composite = ee.Image(ee.Algorithms.If(
                filtered.size().gt(0),
                filtered.median(),
                emptyImageWithBands
            ))
            return composite.set('system:time_start', startDate.millis())
            
        compositeCollection = ee.ImageCollection.fromImages(dateList.map(create_composite))
        
        # ==============================================================================
        # --- Phase 3: Identify NEW Fires (Adapted for Incremental Updates) ---
        # ==============================================================================
        viirsFires = ee.ImageCollection('FIRMS').filterBounds(aoi).filterDate(start_date_filter, end_date_filter)

        def getFirePointsWithDate(image):
            fireDate = image.date()
            firePoints = image.select('confidence').gte(8).selfMask()
            vectors = firePoints.reduceToVectors(geometry=aoi, scale=375, geometryType='centroid', bestEffort=True)
            return vectors.map(lambda f: f.set('fire_date', fireDate))

        allNewFirePoints = viirsFires.map(getFirePointsWithDate).flatten()
        
        riceMap = get_rice_mask_image(RICE_MAP_ASSET_PATH)
        newFiresOnRice = riceMap.eq(1).reduceRegions(
            collection=allNewFirePoints, 
            reducer=ee.Reducer.firstNonNull(), 
            scale=10
        ).filter(ee.Filter.eq('first', 1))

        # Add unique ID and coordinates to each new fire point
        def add_metadata(f):
            pointId = f.get('system:index')
            coords = f.geometry().coordinates()
            return f.set({
                'point_id': pointId,
                'longitude': coords.get(0),
                'latitude': coords.get(1)
            # ⭐️⭐️⭐️ THE FIX IS HERE: Changed the last argument from False to True ⭐️⭐️⭐️
            }).select(['point_id', 'fire_date', 'longitude', 'latitude'], None, True)
        
        burnSamples = newFiresOnRice.map(add_metadata)

        new_fires_count = burnSamples.size().getInfo()
        if new_fires_count == 0:
            print("👍 No new fire points found for the specified test date range.")
            return
        
        print(f"Found {new_fires_count} new fire points on rice cropland.")

        # ==============================================================================
        # --- Phase 4: Extract Time Series (Corrected to Long Format from JS) ---
        # ==============================================================================
        
        def extractTimeSeries(fc, image):
            return image.select(ALL_BANDS).reduceRegions(
                collection=fc,
                reducer=ee.Reducer.mean(),
                scale=10
            ).map(lambda feature: feature.set('image_date', image.date()))

        # composites x points can exceed Earth Engine's ~5000-element interactive
        # query cap for a large batch of new fires (e.g. a historical backfill,
        # or a genuinely busy day in-season) -- batch the points client-side and
        # combine results, rather than one request that gets aborted server-side.
        print(f"⬇️ Fetching data for {new_fires_count} points from GEE... (this may take a moment)")
        num_composites = compositeCollection.size().getInfo()
        point_ids = burnSamples.aggregate_array('point_id').getInfo()
        points_per_batch = max(1, 3000 // max(num_composites, 1))
        batches = [point_ids[i:i + points_per_batch] for i in range(0, len(point_ids), points_per_batch)]
        if len(batches) > 1:
            print(f"   Batching {len(point_ids)} points into {len(batches)} request(s) of up to {points_per_batch} to stay under Earth Engine's query limit.")

        features = []
        for batch_ids in batches:
            batch_points = burnSamples.filter(ee.Filter.inList('point_id', batch_ids))
            batch_series = compositeCollection.map(lambda image: extractTimeSeries(batch_points, image)).flatten()
            features.extend(batch_series.getInfo().get('features', []))

        if not features:
            print("No time-series data extracted for the new fire points.")
            return

        print(f"🔄 Processing {len(features)} time-series observations to load into database.")
        
        fire_points_to_create = {}
        for feature in features:
            props = feature['properties']
            point_id = props['point_id']
            if point_id not in fire_points_to_create:
                fire_points_to_create[point_id] = FirePoint(
                    point_id=point_id,
                    longitude=props['longitude'],
                    latitude=props['latitude'],
                    fire_date=datetime.datetime.fromtimestamp(props['fire_date']['value'] / 1000.0, tz=datetime.timezone.utc),
                    province='Punjab'
                )

        FirePoint.objects.bulk_create(fire_points_to_create.values(), ignore_conflicts=True)
        
        point_ids_to_fetch = fire_points_to_create.keys()
        fire_point_map = {fp.point_id: fp for fp in FirePoint.objects.filter(point_id__in=point_ids_to_fetch)}
        
        observations_to_create = []
        for feature in features:
            props = feature['properties']
            point_id = props['point_id']
            
            fire_point_obj = fire_point_map.get(point_id)
            if not fire_point_obj:
                continue
                
            band_values = [props.get(band) for band in ALL_BANDS]
            if all(v is None for v in band_values):
                continue
            
            observations_to_create.append(
                FireObservation(
                    point=fire_point_obj,
                    image_date=datetime.datetime.fromtimestamp(props['image_date']['value'] / 1000.0, tz=datetime.timezone.utc),
                    NDVI=props.get('NDVI'),
                    NDWI=props.get('NDWI'),
                    NBR=props.get('NBR'),
                    NDRE=props.get('NDRE'),
                    VV=props.get('VV'),
                    VH=props.get('VH')
                )
            )

        if observations_to_create:
            FireObservation.objects.bulk_create(observations_to_create, ignore_conflicts=True)
        
        print(f"✅ Successfully processed and loaded {len(observations_to_create)} observations for {new_fires_count} fire points.")

    except ee.EEException as e:
        print(f"❌ A Google Earth Engine error occurred: {e}")
    except IntegrityError as e:
        print(f"❌ A database integrity error occurred (possibly a race condition): {e}")
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")