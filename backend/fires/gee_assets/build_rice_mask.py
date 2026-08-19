"""
Rebuilds the rice-cropland mask that used to live at a private asset on the
old (now-gone) GEE account. No ground truth or field data is used -- the
mask is derived purely from a known remote-sensing signature:

Rice paddies show a distinctive Sentinel-1 VH backscatter dip at
transplanting/flooding (specular reflection off standing water), followed by
a rise as the canopy develops. Combined with an ESA WorldCover cropland
prefilter (to reject rivers/urban/permanent water) and a Sentinel-2 NDVI
canopy-rise check (to reject wetlands, which show the SAR dip but never grow
a canopy), this gives a defensible dev-scope rice mask.

There is no ground truth available to validate VH_FLOOD_THRESHOLD_DB /
NDVI_CANOPY_THRESHOLD against -- treat this as an approximate v1 and expect
to tune the two constants below after inspecting --dry-run output.

v2 note: a province-wide dry run came back at ~3.65M ha against an official
estimate of ~1.7-2.2M ha for Punjab -- a single-pass "was VH below threshold
at any point in a 2.5-month window" flood check was almost certainly picking
up ordinary monsoon-flooded non-rice fields, not just deliberate paddy
transplanting. Two changes address that: (1) the transplant window is
narrowed to when Punjab rice transplanting actually concentrates rather than
a broad May-mid-July span that includes a lot of pre-monsoon/early-monsoon
noise, and (2) the flood signal now has to persist across multiple
Sentinel-1 passes instead of triggering on a single dip, since real paddy
flooding is sustained for weeks while transient rain-flooding of other
fields typically isn't.
"""
import ee

from .common import get_punjab_aoi, poll_task

CROPLAND_CLASS = 40  # ESA WorldCover v200 "Cropland"
VH_FLOOD_THRESHOLD_DB = -20.0  # VH below this during the transplant window suggests flooding
MIN_FLOOD_PERSISTENCE_HITS = 2  # require the VH dip on at least this many separate S1 passes
NDVI_CANOPY_THRESHOLD = 0.55  # NDVI above this during the canopy window suggests a real crop, not open water


def _mask_s2_clouds(image):
    scl = image.select('SCL')
    good_pixels = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(7))
    return image.updateMask(good_pixels)


def build_rice_mask(season_year):
    """Returns (rice_mask_image, aoi_geometry). Caller decides dry-run stats vs. export."""
    aoi = get_punjab_aoi().geometry()

    cropland = (
        ee.ImageCollection('ESA/WorldCover/v200')
        .first()
        .select('Map')
        .eq(CROPLAND_CLASS)
        .clip(aoi)
    )

    # Narrowed from the original May 1 - Jul 15 span: that included over a
    # month of pre-monsoon/early-monsoon weeks where flooding is more likely
    # to be rain rather than deliberate transplanting. Punjab rice
    # transplanting concentrates in June through early July.
    transplant_start, transplant_end = f'{season_year}-06-01', f'{season_year}-07-10'
    s1_transplant = (
        ee.ImageCollection('COPERNICUS/S1_GRD')
        .filterBounds(aoi)
        .filterDate(transplant_start, transplant_end)
        .filter(ee.Filter.eq('instrumentMode', 'IW'))
        .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH'))
        .filter(ee.Filter.eq('orbitProperties_pass', 'DESCENDING'))
        .select('VH')
        .map(lambda img: img.focal_median(**{'radius': 50, 'units': 'meters'}))
    )
    # Persistence check: count how many separate passes each pixel was below
    # the flood threshold on, rather than just taking the single deepest dip
    # across the whole window. Sustained flooding (paddy) vs. a transient
    # rain-flooded field (most other crops) should separate out here.
    flood_hit_count = s1_transplant.map(lambda img: img.lt(VH_FLOOD_THRESHOLD_DB)).sum().clip(aoi)
    persistent_flood = flood_hit_count.gte(MIN_FLOOD_PERSISTENCE_HITS)

    canopy_start, canopy_end = f'{season_year}-08-01', f'{season_year}-09-30'
    s2_canopy = (
        ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(aoi)
        .filterDate(canopy_start, canopy_end)
        .map(_mask_s2_clouds)
        .map(lambda img: img.normalizedDifference(['B8', 'B4']).rename('NDVI'))
    )
    ndvi_max = s2_canopy.max().clip(aoi)

    rice_mask = (
        cropland
        .And(persistent_flood)
        .And(ndvi_max.gt(NDVI_CANOPY_THRESHOLD))
        .rename('rice')
        .selfMask()
    )
    return rice_mask, aoi


def compute_rice_area_hectares(rice_mask, aoi):
    """Runs the area sum as an async batch export + poll rather than a
    synchronous .getInfo() call. A direct .getInfo() works fine over a small
    AOI (e.g. the old Hafizabad-only scope) but a province-wide composite
    over months of Sentinel-1/2 imagery exceeds GEE's interactive-compute
    time limit ("Computation timed out") even though the batch cluster
    handles the identical computation without issue -- same class of fix as
    export_rice_mask/export_dss_training_table below, just for a scalar
    result instead of a raster/table."""
    from django.conf import settings

    area_m2 = rice_mask.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=aoi, scale=20, maxPixels=1e10, bestEffort=True
    )
    # Export.table.toAsset rejects features with null geometry -- the
    # geometry itself is meaningless here, only the property value matters.
    result_fc = ee.FeatureCollection(
        [ee.Feature(ee.Geometry.Point([0, 0]), {'hectares': ee.Number(area_m2.get('rice')).divide(10000)})]
    )

    scratch_asset_id = f'projects/{settings.GEE_PROJECT_ID}/assets/_scratch_rice_area_hectares'
    try:
        ee.data.deleteAsset(scratch_asset_id)
    except ee.EEException:
        pass
    task = ee.batch.Export.table.toAsset(
        collection=result_fc, description='rice_area_hectares_scratch', assetId=scratch_asset_id
    )
    poll_task(task, label='compute rice area hectares (batch)')

    hectares = ee.FeatureCollection(scratch_asset_id).first().get('hectares').getInfo()
    try:
        ee.data.deleteAsset(scratch_asset_id)
    except ee.EEException:
        pass
    return hectares


def export_rice_mask(rice_mask, aoi, asset_id):
    task = ee.batch.Export.image.toAsset(
        image=rice_mask.toByte(),
        description='rice_mask_punjab',
        assetId=asset_id,
        region=aoi,
        scale=10,
        maxPixels=1e13,
    )
    return poll_task(task, label=f'export rice mask -> {asset_id}')
