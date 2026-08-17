
# fires/views.py
from django.http import JsonResponse, HttpResponseRedirect, FileResponse
from django.utils.dateparse import parse_date
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework.decorators import api_view
from .models import FirePoint, FireObservation, StageTileDate
from .blob_storage import signed_tile_url
from .dashboard import build_dashboard_summary, build_district_summary, list_incidents
import os
import math
from django.http import JsonResponse
import json
import re
METRIC_KEYS = ["NDVI", "NDWI", "NBR", "NDRE", "VV", "VH"]


def _check_scheduler_token(request):
    return (
        settings.CLOUD_SCHEDULER_TOKEN
        and request.headers.get("X-Cloud-Scheduler-Token") == settings.CLOUD_SCHEDULER_TOKEN
    )


@csrf_exempt
@require_POST
def trigger_fetch(request):
    """HTTP trigger for the fire-points fetch job (called by Cloud Scheduler).

    Imports gee_fetcher lazily -- it runs GEE service-account auth as a
    module-level side effect, which needs network access and shouldn't
    happen on every Django process boot, only when this job actually runs.
    """
    if not _check_scheduler_token(request):
        return JsonResponse({"error": "forbidden"}, status=403)
    from .gee_fetcher import fetch_and_load_new_fires
    fetch_and_load_new_fires()
    return JsonResponse({"status": "ok"})


@csrf_exempt
@require_POST
def trigger_stage_fetch(request):
    """Manual-trigger escape hatch for the stage-map pipeline.

    The scheduled path runs this as a Cloud Run Job instead (the pipeline
    takes ~15-20 min); this endpoint exists for on-demand testing. Imported
    lazily for the same reason as trigger_fetch above.
    """
    if not _check_scheduler_token(request):
        return JsonResponse({"error": "forbidden"}, status=403)
    from .stage_fetcher import fetch_and_process_latest_stage_map
    fetch_and_process_latest_stage_map()
    return JsonResponse({"status": "ok"})

def _num(x):
    # Convert to JSON-safe number or None (handles NaN/inf/None)
    try:
        if x is None:
            return None
        f = float(x)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None

# --- Tiles (served from a private B2 bucket via a short-lived signed URL) ---
def serve_tile(request, z, x, y):
    if not settings.B2_BUCKET_NAME:
        # Local dev fallback: no bucket configured, serve straight from disk.
        tile_path = os.path.join(settings.BASE_DIR, "static", f"imgs_pak_punjab/{z}/{x}/{y}.png")
        if os.path.exists(tile_path):
            return FileResponse(open(tile_path, "rb"), content_type="image/png")
        return JsonResponse({"error": "Tile not found"}, status=404)
    blob_path = f"{settings.B2_TILES_PREFIX}/{z}/{x}/{y}.png"
    return HttpResponseRedirect(signed_tile_url(blob_path))

# --- DB-backed version of your CSV endpoint ---
@api_view(['GET'])
def get_fire_timeseries(request):
    try:
        start = (request.GET.get('start') or '').strip()
        end   = (request.GET.get('end') or '').strip()
        region = (request.GET.get('region') or '').strip()
        bbox   = (request.GET.get('bbox') or '').strip()
        pid    = (request.GET.get('point_id') or '').strip()

        print("\n[DEBUG] Incoming request params:")
        print(f"  start={start}, end={end}, region={region}, bbox={bbox}, point_id={pid}")

        points_qs = FirePoint.objects.all()
        print(f"[DEBUG] Initial FirePoints count: {points_qs.count()}")

        if pid:
            variants = {pid, pid.replace(' ', '+'), pid.replace('+', ' ')}
            print(f"[DEBUG] Filtering by point_id variants: {variants}")
            points_qs = points_qs.filter(point_id__in=variants)
            print(f"[DEBUG] Count after point_id filter: {points_qs.count()}")

        if start and end:
            s, e = parse_date(start), parse_date(end)
            print(f"[DEBUG] Parsed dates -> start: {s}, end: {e}")
            if s and e:
                points_qs = points_qs.filter(fire_date__date__gte=s, fire_date__date__lte=e)
                print(f"[DEBUG] Count after date filter: {points_qs.count()}")

        # if region == "Pakistani Punjab":
        #     print("[DEBUG] Applying region filter: province='Punjab'")
        #     points_qs = points_qs.filter(province="Punjab")
        #     print(f"[DEBUG] Count after region filter: {points_qs.count()}")

        if bbox:
            try:
                south, west, north, east = map(float, bbox.split(","))
                print(f"[DEBUG] Applying bbox filter: south={south}, west={west}, north={north}, east={east}")
                points_qs = points_qs.filter(
                    latitude__gte=south, latitude__lte=north,
                    longitude__gte=west, longitude__lte=east
                )
                print(f"[DEBUG] Count after bbox filter: {points_qs.count()}")
            except Exception as ex:
                print(f"[ERROR] Invalid bbox format: {bbox} -> {ex}")

        points = list(points_qs)
        print(f"[DEBUG] Final FirePoints to process: {len(points)}")

        if not points:
            print("[DEBUG] No FirePoints found after filtering.")
            return JsonResponse([] if not pid else {}, safe=False)

        buckets = {
            p.point_id: {
                "point_id": p.point_id,
                "fire_date": p.fire_date.isoformat() if p.fire_date else None,
                "longitude": p.longitude,
                "latitude": p.latitude,
                "image_date": [],
                **{k: [] for k in METRIC_KEYS},
            }
            for p in points
        }

        obs_qs = (
            FireObservation.objects
            .filter(point__in=points)
            .order_by("point__point_id", "image_date")
            .values("point__point_id", "image_date", *METRIC_KEYS)
        )
        print(f"[DEBUG] Observations fetched: {obs_qs.count()}")

        for r in obs_qs:
            pid_key = r["point__point_id"]
            b = buckets.get(pid_key)
            if not b:
                continue
            d = r["image_date"]
            b["image_date"].append((d.date() if hasattr(d, "date") else d).isoformat())
            for k in METRIC_KEYS:
                b[k].append(_num(r[k]))

        data = [b for b in buckets.values() if b["image_date"]]
        print(f"[DEBUG] Points with time series: {len(data)}")

        if pid:
            return JsonResponse(data[0] if data else {
                "point_id": points[0].point_id,
                "fire_date": points[0].fire_date.isoformat() if points[0].fire_date else None,
                "longitude": points[0].longitude,
                "latitude": points[0].latitude,
                "image_date": [],
                **{k: [] for k in METRIC_KEYS},
            }, safe=False, json_dumps_params={"allow_nan": False})

        return JsonResponse(data, safe=False, json_dumps_params={"allow_nan": False})

    except Exception as e:
        print(f"[ERROR] Exception in get_fire_timeseries: {e}")
        return JsonResponse({'error': str(e)}, status=500)


def get_districts(request):
    file_path = os.path.join(settings.BASE_DIR, 'data', 'punjab_districts.geojson')
    with open(file_path, 'r', encoding='utf-8') as f:
        geojson_data = json.load(f)
    return JsonResponse(geojson_data)


@api_view(['GET'])
def get_dashboard_summary(request):
    try:
        window_days = int(request.GET.get('days', 30))
    except (TypeError, ValueError):
        window_days = 30
    window_days = max(1, min(window_days, 365))
    return JsonResponse(build_dashboard_summary(window_days=window_days))


@api_view(['GET'])
def get_district_summary(request):
    district = (request.GET.get('district') or '').strip()
    if not district:
        return JsonResponse({"error": "district query param is required"}, status=400)
    try:
        window_days = int(request.GET.get('days', 7))
    except (TypeError, ValueError):
        window_days = 7
    try:
        trend_days = int(request.GET.get('trend_days', 90))
    except (TypeError, ValueError):
        trend_days = 90
    window_days = max(1, min(window_days, 365))
    trend_days = max(1, min(trend_days, 365))

    summary = build_district_summary(district, window_days=window_days, trend_days=trend_days)
    if summary is None:
        return JsonResponse({"error": f"Unknown district: {district}"}, status=404)
    return JsonResponse(summary)


@api_view(['GET'])
def get_incidents(request):
    district = (request.GET.get('district') or '').strip() or None
    start = (request.GET.get('start') or '').strip() or None
    end = (request.GET.get('end') or '').strip() or None
    try:
        limit = int(request.GET.get('limit', 500))
    except (TypeError, ValueError):
        limit = 500
    limit = max(1, min(limit, 2000))

    incidents = list_incidents(district_name=district, start=start, end=end, limit=limit)
    return JsonResponse({"incidents": incidents, "total": len(incidents), "start": start, "end": end})











# -------------------- NEW CODE --------------------

def serve_stage_tile(request, date, z, x, y):
    """Serves a single growth-stage map tile via a signed B2 URL."""
    if not re.match(r"^\d{8}$", str(date)):
        return JsonResponse({"error": "Invalid date format. Expected YYYYMMDD."}, status=400)

    if not settings.B2_BUCKET_NAME:
        # Local dev fallback: no bucket configured, serve straight from disk.
        tile_path = os.path.join(settings.BASE_DIR, "static", "stage_tiles", str(date), str(z), str(x), f"{y}.png")
        if os.path.exists(tile_path):
            return FileResponse(open(tile_path, "rb"), content_type="image/png")
        return JsonResponse({"error": "Stage tile not found"}, status=404)

    blob_path = f"{settings.B2_STAGE_TILES_PREFIX}/{date}/{z}/{x}/{y}.png"
    return HttpResponseRedirect(signed_tile_url(blob_path))


@api_view(['GET'])
def get_stage_dates(request):
    """Returns a structured list of available stage-tile dates for the
    archive sliders and 'latest' toggle, sourced from StageTileDate rows
    (populated by the stage-fetch pipeline) rather than a local directory
    listing."""
    try:
        if not settings.B2_BUCKET_NAME:
            # Local dev fallback: no bucket configured, scan disk like before.
            stage_dir = os.path.join(settings.BASE_DIR, "static", "stage_tiles")
            all_dates = sorted(
                name for name in os.listdir(stage_dir)
                if os.path.isdir(os.path.join(stage_dir, name)) and re.match(r"^\d{8}$", name)
            ) if os.path.isdir(stage_dir) else []
        else:
            all_dates = list(StageTileDate.objects.values_list('date_str', flat=True))

        if not all_dates:
            return JsonResponse({'dates': [], 'years': {}, 'latest': None}, safe=False)

        dates_by_year = {}
        for date_str in all_dates:
            dates_by_year.setdefault(date_str[:4], []).append(date_str)

        response_data = {
            'dates': all_dates,
            'years': dates_by_year,
            'latest': all_dates[-1],
        }

        return JsonResponse(response_data, safe=False)

    except Exception as e:
        print(f"[ERROR] Exception in get_stage_dates: {e}")
        return JsonResponse({'error': str(e)}, status=500)
    
    


from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2
from django.http import HttpResponse
from rest_framework.decorators import api_view
from .models import FirePoint
from .pdf_report import generate_fire_pdf


# ✅ Helper: Haversine distance in km
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


@api_view(['GET'])
def fire_report(request, point_id):
    try:
        fire_point = FirePoint.objects.get(point_id=point_id)
    except FirePoint.DoesNotExist:
        return HttpResponse("Fire point not found", status=404)

    radius_km = 10
    now = datetime.now().date()
    one_month_ago = fire_point.fire_date.date() - timedelta(days=7)

    all_candidates = FirePoint.objects.exclude(point_id=point_id).filter(
        fire_date__date__gte=one_month_ago,
        fire_date__date__lte=fire_point.fire_date.date() + timedelta(days=7)
    )

    nearby_count = 0
    for p in all_candidates:
        distance = haversine(fire_point.latitude, fire_point.longitude, p.latitude, p.longitude)
        if distance <= radius_km:
            nearby_count += 1


    seasonal_count = FirePoint.objects.filter(
        fire_date__year=fire_point.fire_date.year
    ).exclude(point_id=point_id).count()

    history_counts = {
        '7_days': nearby_count,   
        'seasonal': seasonal_count,
    }


    pdf_bytes = generate_fire_pdf(fire_point, history_counts)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="fire_report_{point_id}.pdf"'
    return response







######HEATMAP CODE STARTS HERE######
from django.http import JsonResponse, HttpResponse
from django.utils.dateparse import parse_date
from django.conf import settings
from rest_framework.decorators import api_view
import os
import math
import json
import re
import datetime
import requests # Make sure you've run: pip install requests

# --- GEE Imports ---
import ee

# --- Google Auth Imports (Copied from stage_fetcher.py) ---
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# --- Model Imports ---
from .models import FirePoint, FireObservation
from .pdf_report import generate_fire_pdf

# --- Constants ---
GEE_PROJECT_ID = settings.GEE_PROJECT_ID
SCOPES = ['https://www.googleapis.com/auth/earthengine', 'https://www.googleapis.com/auth/drive']
TOKEN_PATH = settings.GEE_OAUTH_TOKEN_PATH

METRIC_KEYS = ["NDVI", "NDWI", "NBR", "NDRE", "VV", "VH"]

# --- S5P Heatmap Configuration ---
# --- S5P Heatmap Configuration ---
HEATMAP_PALETTE = ['black', 'blue', 'purple', 'cyan', 'green', 'yellow', 'red']

HEATMAP_CONFIG = {
    'co': {
        # --- THIS LINE IS THE FIX ---
        'collection': 'COPERNICUS/S5P/NRTI/L3_CO', 
        'band': 'CO_column_number_density',
        'vis': {'min': 0.0, 'max': 0.05, 'palette': HEATMAP_PALETTE}
    },
    'so2': {
        'collection': 'COPERNICUS/S5P/NRTI/L3_SO2',
        'band': 'SO2_column_number_density',
        'vis': {'min': 0.0, 'max': 0.0005, 'palette': HEATMAP_PALETTE}
    },
    'no2': {
        'collection': 'COPERNICUS/S5P/NRTI/L3_NO2',
        'band': 'tropospheric_NO2_column_number_density',
        'vis': {'min': 0.0, 'max': 0.0002, 'palette': HEATMAP_PALETTE}
    },
    'aai': {
        'collection': 'COPERNICUS/S5P/NRTI/L3_AER_AI',
        'band': 'absorbing_aerosol_index',
        'vis': {'min': -1, 'max': 2.0, 'palette': HEATMAP_PALETTE}
    }
}
# --- End Configuration ---
def _get_user_credentials():
    """Gets user credentials using the token.json/credentials.json flow."""
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing GEE user credentials...")
            creds.refresh(Request())
        else:
            # This view runs inside an HTTP request handler -- there is no
            # browser to complete an interactive consent flow with, so
            # run_local_server() would just hang the request forever waiting
            # for a callback that can never arrive. Fail fast instead.
            raise RuntimeError(
                "GEE user credentials are missing or unrefreshable (no valid token.json). "
                "Run `python manage.py run_stage_fetcher` from a terminal once to "
                "(re)authenticate interactively before using this endpoint."
            )
        # Save the refreshed credentials for next run. On Cloud Run, TOKEN_PATH
        # is a read-only Secret Manager mount, so persisting the refresh can
        # fail -- that's fine, the in-memory creds are still valid for this
        # process's lifetime, and a new instance will just refresh again.
        try:
            with open(TOKEN_PATH, 'w') as token:
                token.write(creds.to_json())
        except OSError as e:
            print(f"Could not persist refreshed GEE token to {TOKEN_PATH}: {e}")
    return creds
# ==============

# =================================================================================
# ⭐️ Heatmap Tile Server (Refactored with User Auth & Clipping)
# =================================================================================
def serve_heatmap_tile(request, gas_type, z, x, y):
    """
    Generates and serves a single S5P heatmap tile as a proxy.
    Uses the user credential auth flow.
    """
    if gas_type not in HEATMAP_CONFIG:
        return JsonResponse({"error": "Invalid heatmap type"}, status=404)
    
    try:
        # --- MODIFIED: Authenticate using user credentials ---
        print(f"[{datetime.datetime.utcnow()}] Authenticating GEE for heatmap tile...")
        creds = _get_user_credentials()
        ee.Initialize(project=GEE_PROJECT_ID, credentials=creds)
        print("✅ GEE auth successful for heatmap.")
        # --- END MODIFICATION ---

        config = HEATMAP_CONFIG[gas_type]
        
        # 1. Define Date Range (7-day lookback from today)
        end_date = ee.Date(datetime.datetime.utcnow())
        start_date = end_date.advance(-7, 'day')

        # --- NEW: Define Area of Interest (AOI) ---
        adminLevel2 = ee.FeatureCollection("FAO/GAUL/2015/level2")
        hafizabad = adminLevel2.filter(ee.Filter.And(
            ee.Filter.eq('ADM0_NAME', 'Pakistan'),
            ee.Filter.eq('ADM1_NAME', 'Punjab'),
            ee.Filter.eq('ADM2_NAME', 'Hafizabad District')
        ))
        # --- END NEW ---

        # 2. Create the GEE Image and CLIP IT
        image = (
            ee.ImageCollection(config['collection'])
            .filterDate(start_date, end_date)
            .select(config['band'])
            .mean()
            .clip(hafizabad)  # <-- THIS IS THE NEW LINE
        )
        
        # 3. Get the GEE Tile URL
        map_id = image.getMapId(config['vis'])
        tile_url = map_id['tile_fetcher'].url_format
        
        # 4. Format the URL with the requested tile coordinates
        gee_url = tile_url.format(x=x, y=y, z=z)
        
        # 5. Fetch the tile from GEE and stream it back
        response = requests.get(gee_url, stream=True, timeout=30)

        if not response.ok:
            return HttpResponse(f"GEE tile server error: {response.status_code}", status=response.status_code)

        # Stream the image content
        return HttpResponse(
            response.content,
            content_type=response.headers.get('Content-Type', 'image/png')
        )

    except ee.EEException as e:
        print(f"❌ GEE Error in heatmap: {e}")
        return JsonResponse({"error": f"GEE Error: {e}"}, status=500)
    except Exception as e:
        import traceback
        print(f"❌ Server Error in heatmap: {e}\n{traceback.format_exc()}")
        return JsonResponse({"error": f"Server Error: {e}"}, status=500)