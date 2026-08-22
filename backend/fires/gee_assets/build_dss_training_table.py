"""
Rebuilds the DSS (Days-Since-Sowing) training table that used to live at a
private asset on the old (now-gone) GEE account, with no access to the
original field-collected ground truth.

Both features and labels are derived from fresh imagery instead:
- Sample points inside the rice mask (see build_rice_mask.py).
- Per point, the date of that point's Sentinel-1 VH minimum during the
  transplant window is used as a proxy "transplant/sowing date" (the same
  flood-signature reasoning as the rice mask, just per-point instead of
  per-pixel-for-the-whole-district, which is cheap for a few hundred points).
- Per point, every later composite in the season gets DSS = image_date -
  transplant_date as its label, with NDVI/NDWI/VH/VV/VH_VV_ratio/day_of_year/
  days_since_season_start as features -- the same feature set
  stage_fetcher.py's classifier already expects.

Points where no clear transplant signal is found (missing imagery, no VH
dip) are dropped rather than guessed at.
"""
import datetime

import ee

from .common import poll_task

NUM_SAMPLE_POINTS = 400
TRANSPLANT_COMPOSITE_INTERVAL_DAYS = 5
SEASON_COMPOSITE_INTERVAL_DAYS = 10


def _prep_s2(image):
    scl = image.select('SCL')
    good_pixels = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(7))
    ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
    ndwi = image.normalizedDifference(['B3', 'B8']).rename('NDWI')
    return image.addBands([ndvi, ndwi]).updateMask(good_pixels).select(['NDVI', 'NDWI'])


def _prep_s1(image):
    smoothed = image.focal_median(**{'radius': 50, 'units': 'meters'})
    return smoothed.select(['VV', 'VH'])


def _empty_bands(band_names):
    zeros = ee.List.repeat(0, ee.List(band_names).length())
    return ee.Image.constant(zeros).toFloat().rename(band_names).updateMask(ee.Image(0))


def _s2_for_window(aoi, start, end):
    return ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(aoi).filterDate(start, end).map(_prep_s2)


def _s1_for_window(aoi, start, end):
    return (
        ee.ImageCollection('COPERNICUS/S1_GRD')
        .filterBounds(aoi)
        .filterDate(start, end)
        .filter(ee.Filter.eq('instrumentMode', 'IW'))
        .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH'))
        .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
        .filter(ee.Filter.eq('orbitProperties_pass', 'DESCENDING'))
        .map(_prep_s1)
    )


def _composite_collection(aoi, start_date, end_date, interval_days):
    # Build window boundaries as plain Python dates/strings, and build a fresh,
    # independently-filtered S1/S2 query PER WINDOW rather than re-filtering one
    # shared collection object multiple times -- re-filtering a shared object
    # per window silently produced empty results here (confirmed by direct
    # comparison), even though the identical filters as independent queries per
    # window worked correctly. Only ~16-30 windows total, so the extra queries
    # cost nothing meaningful.
    start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.datetime.strptime(end_date, '%Y-%m-%d')
    window_starts = []
    d = start_dt
    while d <= end_dt:
        window_starts.append(d)
        d += datetime.timedelta(days=interval_days)

    composites = []
    for window_start_dt in window_starts:
        window_start_str = window_start_dt.strftime('%Y-%m-%d')
        window_end_str = (window_start_dt + datetime.timedelta(days=interval_days)).strftime('%Y-%m-%d')
        # Start from a fully-masked placeholder and let real data overwrite it where it
        # exists -- avoids ee.Algorithms.If, which blocks Earth Engine's optimizer from
        # batching/parallelizing this across all composite windows and is dramatically
        # slower in practice than unconditional band algebra.
        s2c = _empty_bands(['NDVI', 'NDWI']).addBands(_s2_for_window(aoi, window_start_str, window_end_str).median(), overwrite=True)
        s1c = _empty_bands(['VV', 'VH']).addBands(_s1_for_window(aoi, window_start_str, window_end_str).median(), overwrite=True)
        composite = s2c.addBands(s1c).set('system:time_start', ee.Date(window_start_str).millis())
        composites.append(composite)

    return ee.ImageCollection(composites)


MAX_ROWS_PER_QUERY = 3000  # stay well under Earth Engine's ~5000-element interactive query cap


def _reduce_series(composites, sample_points, bands, scale=10):
    print(f'[_reduce_series] bands={bands} scale={scale}')
    n_composites = composites.size().getInfo()
    first_bands = ee.Image(composites.first()).bandNames().getInfo()
    print(f'[_reduce_series] num composites={n_composites} first_composite_bands={first_bands}')

    # Reducer.first()'s output property is literally named "first", not the band
    # name -- forEachBand() repeats the reducer across a reference image's bands
    # and names each output after its band, which handles both the single- and
    # multi-band cases correctly (manual .repeat(n)/.setOutputs(...) juggling
    # kept hitting mismatched-arity errors or scalar-vs-list inconsistencies).
    reference_image = ee.Image(composites.first()).select(bands)
    reducer = ee.Reducer.first().forEachBand(reference_image)

    def extract(fc, image):
        return image.select(bands).reduceRegions(
            collection=fc, reducer=reducer, scale=scale
        ).map(lambda f: f.set('image_date_millis', image.date().millis()))

    # composites x points can exceed Earth Engine's interactive query cap
    # (~5000 elements) for a full season -- batch the points client-side and
    # combine results, rather than one request that gets aborted server-side.
    point_ids = sample_points.aggregate_array('point_id').getInfo()
    points_per_batch = max(1, MAX_ROWS_PER_QUERY // n_composites)
    batches = [point_ids[i:i + points_per_batch] for i in range(0, len(point_ids), points_per_batch)]
    print(f'[_reduce_series] {len(point_ids)} points, batching into {len(batches)} batch(es) of up to {points_per_batch}')

    features = []
    for batch_ids in batches:
        batch_points = sample_points.filter(ee.Filter.inList('point_id', batch_ids))
        features.extend(composites.map(lambda image: extract(batch_points, image)).flatten().getInfo()['features'])

    n_with_data = sum(1 for f in features if any(f['properties'].get(b) is not None for b in bands))
    print(f'[_reduce_series] total rows={len(features)} rows_with_any_real_value={n_with_data}')
    if features:
        print(f'[_reduce_series] sample row properties: {features[0]["properties"]}')
    return features


def _find_transplant_dates(aoi, sample_points, season_year):
    start, end = f'{season_year}-05-01', f'{season_year}-07-15'
    composites = _composite_collection(aoi, start, end, TRANSPLANT_COMPOSITE_INTERVAL_DAYS)
    rows = _reduce_series(composites, sample_points, ['VH'])

    best_by_point = {}
    for row in rows:
        props = row['properties']
        vh = props.get('VH')
        if vh is None:
            continue
        point_id = props['point_id']
        if point_id not in best_by_point or vh < best_by_point[point_id][1]:
            best_by_point[point_id] = (props['image_date_millis'], vh)
    return {pid: millis for pid, (millis, _vh) in best_by_point.items()}


def build_dss_training_table(season_year):
    """Returns an ee.FeatureCollection ready to inspect (.size()/.aggregate_*) or export."""
    from .common import get_punjab_aoi, get_rice_mask_image
    from django.conf import settings

    aoi = get_punjab_aoi().geometry()
    rice_mask = get_rice_mask_image(settings.GEE_RICE_MASK_ASSET_ID).eq(1)

    sample_points = rice_mask.selfMask().sample(
        region=aoi, scale=30, numPixels=NUM_SAMPLE_POINTS, seed=42, geometries=True
    )
    sample_points = sample_points.map(lambda f: f.set('point_id', f.get('system:index')))

    transplant_dates = _find_transplant_dates(aoi, sample_points, season_year)
    if not transplant_dates:
        raise RuntimeError(
            "No transplant-date signal found for any sampled point -- check the rice mask "
            "and Sentinel-1 coverage over the transplant window before proceeding."
        )

    season_start = ee.Date(f'{season_year}-05-15')
    season_start_millis = season_start.millis().getInfo()

    full_season_composites = _composite_collection(
        aoi, f'{season_year}-05-01', f'{season_year}-11-30', SEASON_COMPOSITE_INTERVAL_DAYS
    )
    rows = _reduce_series(full_season_composites, sample_points, ['NDVI', 'NDWI', 'VV', 'VH'])

    features = []
    for row in rows:
        props = row['properties']
        point_id = props['point_id']
        transplant_millis = transplant_dates.get(point_id)
        if transplant_millis is None:
            continue
        vv, vh = props.get('VV'), props.get('VH')
        ndvi, ndwi = props.get('NDVI'), props.get('NDWI')
        if None in (vv, vh, ndvi, ndwi) or vv == 0:
            continue

        image_millis = props['image_date_millis']
        image_date = datetime.datetime.utcfromtimestamp(image_millis / 1000)
        dss = (image_millis - transplant_millis) / (1000 * 60 * 60 * 24)
        if dss < 0:
            continue  # composite predates this point's own transplant signal

        lon, lat = row['geometry']['coordinates']
        features.append(ee.Feature(ee.Geometry.Point([lon, lat]), {
            'NDVI': ndvi,
            'NDWI': ndwi,
            'VV': vv,
            'VH': vh,
            'VH_VV_ratio': vh / vv,
            'day_of_year': image_date.timetuple().tm_yday,
            'days_since_season_start': (image_millis - season_start_millis) / (1000 * 60 * 60 * 24),
            'DSS': dss,
        }))

    return ee.FeatureCollection(features)


def export_dss_training_table(training_table, asset_id):
    task = ee.batch.Export.table.toAsset(
        collection=training_table,
        description='dss_training_table_punjab',
        assetId=asset_id,
    )
    return poll_task(task, label=f'export DSS training table -> {asset_id}')
