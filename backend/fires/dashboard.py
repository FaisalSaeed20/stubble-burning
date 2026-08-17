# fires/dashboard.py
"""Aggregation/geo logic for the Provincial Summary dashboard.

Kept separate from views.py (already a large file mixing tiles, heatmaps,
PDF reports, and GEE triggers) since this is a distinct concern: turning
raw FirePoint rows into dashboard-ready summary numbers.
"""
import datetime
import json
import os
from functools import lru_cache

from django.conf import settings
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils.dateparse import parse_date
from shapely.geometry import Point, shape
from shapely.prepared import prep

from .models import FirePoint, RiceAreaEstimate, StageTileDate

DISTRICT_NAME_KEY = "ADM2_EN"

STAGE_LABELS = {
    1: "Transplanting",
    2: "Vegetative",
    3: "Reproductive",
    4: "Ripening",
    5: "Maturity/Harvest",
}

# Matches fires/stage_fetcher.py's COLOR_MAP so the map overlay and this
# distribution bar use the same color per stage.
STAGE_COLORS = {
    1: "#000080",
    2: "#00b359",
    3: "#e6c200",
    4: "#f97316",
    5: "#8b4513",
}

# Every existing GEE asset (rice mask, DSS training table, stage classifier)
# is scoped to this district only -- see fires/gee_assets/common.py.
HAFIZABAD_DISTRICT_NAME = "Hafizabad"


@lru_cache(maxsize=1)
def _load_district_polygons():
    path = os.path.join(settings.BASE_DIR, "data", "punjab_districts.geojson")
    with open(path, "r", encoding="utf-8") as f:
        geojson = json.load(f)
    return [
        (feature["properties"].get(DISTRICT_NAME_KEY, ""), prep(shape(feature["geometry"])))
        for feature in geojson["features"]
    ]


def compute_district_counts():
    polygons = _load_district_polygons()
    counts = {name: 0 for name, _ in polygons}

    for longitude, latitude in FirePoint.objects.values_list("longitude", "latitude"):
        if longitude is None or latitude is None:
            continue
        point = Point(longitude, latitude)
        for name, prepared_geom in polygons:
            if prepared_geom.contains(point):
                counts[name] += 1
                break

    return sorted(
        ({"district": name, "count": count} for name, count in counts.items()),
        key=lambda row: row["count"],
        reverse=True,
    )


def compute_active_fires(window_days):
    today = datetime.date.today()
    window_start = today - datetime.timedelta(days=window_days - 1)
    count = FirePoint.objects.filter(fire_date__date__gte=window_start, fire_date__date__lte=today).count()

    this_week_start = today - datetime.timedelta(days=6)
    prev_week_start = today - datetime.timedelta(days=13)
    prev_week_end = today - datetime.timedelta(days=7)
    this_week = FirePoint.objects.filter(fire_date__date__gte=this_week_start, fire_date__date__lte=today).count()
    prev_week = FirePoint.objects.filter(fire_date__date__gte=prev_week_start, fire_date__date__lte=prev_week_end).count()

    trend_pct = round((this_week - prev_week) / prev_week * 100, 1) if prev_week > 0 else None

    return {
        "count": count,
        "window_days": window_days,
        "trend_pct": trend_pct,
        "trend_window_label": "vs last week",
    }


def compute_seasonal_trend(days=90):
    today = datetime.date.today()
    start = today - datetime.timedelta(days=days - 1)

    rows = (
        FirePoint.objects.filter(fire_date__date__gte=start, fire_date__date__lte=today)
        .annotate(day=TruncDate("fire_date"))
        .values("day")
        .annotate(count=Count("id"))
    )
    counts_by_day = {row["day"]: row["count"] for row in rows}

    daily = []
    for offset in range(days):
        day = start + datetime.timedelta(days=offset)
        daily.append({"date": day.isoformat(), "count": counts_by_day.get(day, 0)})

    return {"start_date": start.isoformat(), "end_date": today.isoformat(), "days": daily}


def get_recent_points(window_days, limit=2000):
    today = datetime.date.today()
    window_start = today - datetime.timedelta(days=window_days - 1)
    rows = (
        FirePoint.objects.filter(fire_date__date__gte=window_start, fire_date__date__lte=today)
        .order_by("-fire_date")
        .values("point_id", "latitude", "longitude", "fire_date")[:limit]
    )
    return [
        {
            "point_id": row["point_id"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "fire_date": row["fire_date"].isoformat() if row["fire_date"] else None,
        }
        for row in rows
    ]


def get_at_risk_hectares():
    latest = RiceAreaEstimate.objects.order_by("-computed_at").first()
    return latest.hectares if latest else None


def get_dominant_crop_stage():
    latest = StageTileDate.objects.exclude(dominant_stage__isnull=True).order_by("-date_str").first()
    if not latest:
        return None, None
    label = f"Stage {latest.dominant_stage}"
    sublabel = STAGE_LABELS.get(latest.dominant_stage)
    return label, sublabel


def _get_district_polygon(district_name):
    for name, prepared_geom in _load_district_polygons():
        if name == district_name:
            return prepared_geom
    return None


def _points_in_polygon(polygon, queryset):
    matches = []
    for point_id, longitude, latitude, fire_date in queryset.values_list(
        "point_id", "longitude", "latitude", "fire_date"
    ):
        if longitude is None or latitude is None:
            continue
        if polygon.contains(Point(longitude, latitude)):
            matches.append((point_id, longitude, latitude, fire_date))
    return matches


def compute_district_active_fires(polygon, window_days):
    today = datetime.date.today()
    prev_week_start = today - datetime.timedelta(days=13)
    matches = _points_in_polygon(polygon, FirePoint.objects.filter(fire_date__date__gte=prev_week_start))

    window_start = today - datetime.timedelta(days=window_days - 1)
    this_week_start = today - datetime.timedelta(days=6)
    prev_week_end = today - datetime.timedelta(days=7)

    count = this_week = prev_week = 0
    for _, _, _, fire_date in matches:
        fdate = fire_date.date() if fire_date else None
        if not fdate:
            continue
        if fdate >= window_start:
            count += 1
        if fdate >= this_week_start:
            this_week += 1
        if prev_week_start <= fdate <= prev_week_end:
            prev_week += 1

    trend_pct = round((this_week - prev_week) / prev_week * 100, 1) if prev_week > 0 else None
    return {"count": count, "window_days": window_days, "trend_pct": trend_pct, "trend_window_label": "vs last week"}


def get_district_points(polygon, days=90, limit=2000):
    today = datetime.date.today()
    start = today - datetime.timedelta(days=days - 1)
    matches = _points_in_polygon(
        polygon, FirePoint.objects.filter(fire_date__date__gte=start).order_by("-fire_date")[:limit]
    )
    return [
        {
            "point_id": point_id,
            "latitude": latitude,
            "longitude": longitude,
            "fire_date": fire_date.isoformat() if fire_date else None,
        }
        for point_id, longitude, latitude, fire_date in matches
    ]


def get_district_trend(polygon, days=90):
    today = datetime.date.today()
    start = today - datetime.timedelta(days=days - 1)

    counts_by_day = {}
    matches = _points_in_polygon(polygon, FirePoint.objects.filter(fire_date__date__gte=start))
    for _, _, _, fire_date in matches:
        if not fire_date:
            continue
        day = fire_date.date()
        counts_by_day[day] = counts_by_day.get(day, 0) + 1

    daily = []
    for offset in range(days):
        day = start + datetime.timedelta(days=offset)
        daily.append({"date": day.isoformat(), "count": counts_by_day.get(day, 0)})
    return {"start_date": start.isoformat(), "end_date": today.isoformat(), "days": daily}


def get_district_at_risk_hectares(district_name):
    if district_name != HAFIZABAD_DISTRICT_NAME:
        return None
    return get_at_risk_hectares()


def get_district_crop_stage_distribution(district_name):
    if district_name != HAFIZABAD_DISTRICT_NAME:
        return None
    latest = StageTileDate.objects.exclude(stage_pixel_counts__isnull=True).order_by("-date_str").first()
    if not latest or not latest.stage_pixel_counts:
        return None
    counts = {int(k): v for k, v in latest.stage_pixel_counts.items()}
    total = sum(counts.values())
    if not total:
        return None
    return {
        "date": latest.date_str,
        "stages": [
            {
                "stage": stage,
                "label": STAGE_LABELS.get(stage, f"Stage {stage}"),
                "pct": round(count / total * 100, 1),
                "color": STAGE_COLORS.get(stage, "#999999"),
            }
            for stage, count in sorted(counts.items())
        ],
    }


def build_district_summary(district_name, window_days=7, trend_days=90):
    polygon = _get_district_polygon(district_name)
    if polygon is None:
        return None
    return {
        "district": district_name,
        "active_fires": compute_district_active_fires(polygon, window_days),
        "trend": get_district_trend(polygon, trend_days),
        "points": get_district_points(polygon, trend_days),
        "at_risk_hectares": get_district_at_risk_hectares(district_name),
        "crop_stage_distribution": get_district_crop_stage_distribution(district_name),
    }


def build_dashboard_summary(window_days=30, trend_days=90):
    district_counts = compute_district_counts()
    at_risk_hectares = get_at_risk_hectares()
    dominant_crop_stage, dominant_crop_stage_label = get_dominant_crop_stage()

    missing = []
    if at_risk_hectares is None:
        missing.append("At-Risk Hectares (run `manage.py build_rice_mask` to compute it)")
    if dominant_crop_stage is None:
        missing.append("Dominant Crop Stage (computed automatically the next time the stage-fetch pipeline runs)")

    return {
        "active_fires": compute_active_fires(window_days),
        "trend": compute_seasonal_trend(trend_days),
        "district_counts": district_counts,
        "top_districts": district_counts[:5],
        "recent_points": get_recent_points(window_days),
        "at_risk_hectares": at_risk_hectares,
        "dominant_crop_stage": dominant_crop_stage,
        "dominant_crop_stage_label": dominant_crop_stage_label,
        "placeholders_note": (
            "Not yet available: " + "; ".join(missing) if missing else None
        ),
    }


def resolve_district(longitude, latitude):
    if longitude is None or latitude is None:
        return None
    point = Point(longitude, latitude)
    for name, prepared_geom in _load_district_polygons():
        if prepared_geom.contains(point):
            return name
    return None


def list_incidents(district_name=None, start=None, end=None, limit=500):
    qs = FirePoint.objects.all().order_by("-fire_date")
    start_date = parse_date(start) if start else None
    end_date = parse_date(end) if end else None
    if start_date:
        qs = qs.filter(fire_date__date__gte=start_date)
    if end_date:
        qs = qs.filter(fire_date__date__lte=end_date)

    rows = []
    for point_id, longitude, latitude, fire_date in qs.values_list(
        "point_id", "longitude", "latitude", "fire_date"
    ):
        resolved = resolve_district(longitude, latitude)
        if district_name and resolved != district_name:
            continue
        rows.append(
            {
                "point_id": point_id,
                "district": resolved,
                "fire_date": fire_date.isoformat() if fire_date else None,
            }
        )
        if len(rows) >= limit:
            break
    return rows
