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
"""
import ee

from .common import get_hafizabad_aoi, poll_task

CROPLAND_CLASS = 40  # ESA WorldCover v200 "Cropland"
VH_FLOOD_THRESHOLD_DB = -20.0  # VH below this during the transplant window suggests flooding
NDVI_CANOPY_THRESHOLD = 0.55  # NDVI above this during the canopy window suggests a real crop, not open water


def _mask_s2_clouds(image):
    scl = image.select('SCL')
    good_pixels = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(7))
    return image.updateMask(good_pixels)


def build_rice_mask(season_year):
    """Returns (rice_mask_image, aoi_geometry). Caller decides dry-run stats vs. export."""
    aoi = get_hafizabad_aoi().geometry()

    cropland = (
        ee.ImageCollection('ESA/WorldCover/v200')
        .first()
        .select('Map')
        .eq(CROPLAND_CLASS)
        .clip(aoi)
    )

    transplant_start, transplant_end = f'{season_year}-05-01', f'{season_year}-07-15'
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
    vh_min = s1_transplant.min().clip(aoi)

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
        .And(vh_min.lt(VH_FLOOD_THRESHOLD_DB))
        .And(ndvi_max.gt(NDVI_CANOPY_THRESHOLD))
        .rename('rice')
        .selfMask()
    )
    return rice_mask, aoi


def compute_rice_area_hectares(rice_mask, aoi):
    area_m2 = rice_mask.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=aoi, scale=20, maxPixels=1e10, bestEffort=True
    )
    return ee.Number(area_m2.get('rice')).divide(10000).getInfo()


def export_rice_mask(rice_mask, aoi, asset_id):
    task = ee.batch.Export.image.toAsset(
        image=rice_mask.toByte(),
        description='rice_mask_hafizabad',
        assetId=asset_id,
        region=aoi,
        scale=10,
        maxPixels=1e13,
    )
    return poll_task(task, label=f'export rice mask -> {asset_id}')
