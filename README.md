# Punjab Rice Stubble Burning Monitor

**Live site: [punjab-stubble-monitor-coders-65a4.vercel.app](https://punjab-stubble-monitor-coders-65a4.vercel.app)**

Every year, right after the rice harvest, farmers across Punjab burn their leftover stubble to clear fields quickly and cheaply for the next planting cycle. It's fast and it's cheap — and it's also one of the biggest contributors to the smog that blankets cities like Lahore every October and November, sending air quality into hazardous territory and hospitals into overdrive.

The problem is nobody has good, real-time visibility into where this is actually happening. Government monitoring is sparse, manual, and slow. Meanwhile, satellites fly over this exact region every single day, quietly collecting exactly the data you'd need to track it.

This project is an attempt to close that gap: a live dashboard that watches stubble burning as it happens, using free public satellite data instead of manual reporting on the ground.

## What it actually does

- **🔥 Detects active fires** using NASA FIRMS thermal anomaly data, cross-referenced against Sentinel-1/Sentinel-2 imagery for confirmation.
- **🌾 Tracks rice crop growth stages** (transplanting → vegetative → reproductive → ripening → harvest) with a Random Forest classifier trained on Sentinel-1 SAR + Sentinel-2 optical bands — because stubble burning only makes sense once a field has actually been harvested, so knowing the crop stage tells you *where burning is likely to happen next*, not just where it already did.
- **💨 Overlays live air quality data** — CO, SO₂, NO₂, and aerosol index — from Sentinel-5P, so you can visually connect fire activity to the pollution it's actually causing.
- **📊 Rolls all of it into a dashboard** with four views:
  - **Provincial Summary** — stat cards, a district risk map, and seasonal trend charts
  - **District Analytics** — per-district fire stats, crop-stage distribution, and atmospheric layer overlays
  - **Incident Explorer** — a filterable, searchable table of every fire detection, each with an auto-generated PDF report
  - **Interactive Map** — the raw geospatial view, with fire clustering and archived crop-stage tile layers

## Current scope

Everything right now is piloted on **Hafizabad District** as a proof of concept — one district, end to end, rather than a shallow province-wide sketch. The architecture (AOI resolution, GEE asset pipeline, dashboard aggregation) is written so that scaling out to the rest of Punjab is a configuration change, not a rewrite, but that expansion hasn't happened yet.

## Tech stack

**Backend** — Django 5 + Django REST Framework, running the whole geospatial pipeline through Google Earth Engine (`earthengine-api`), with `rasterio`/`rio-tiler` for tiling exported GeoTIFFs into slippy-map tiles, and `scikit-learn` for the standalone burn classifier.

**Frontend** — Next.js 15 (App Router) + React 19, Tailwind CSS, Leaflet/`react-leaflet` for the maps, Chart.js for the trend charts, and `leaflet.markercluster` (wired up manually rather than through a React wrapper) for fire clustering.

**Data sources** — NASA FIRMS (active fire detections), Sentinel-1 (SAR, for flood/canopy signals independent of cloud cover), Sentinel-2 (optical indices), Sentinel-5P (atmospheric chemistry).

**Infrastructure** — Django backend on [Render](https://render.com) (free tier), Postgres on [Neon](https://neon.tech) (serverless, free tier), tile storage on [Backblaze B2](https://www.backblaze.com/cloud-storage) (S3-compatible, free tier), frontend on [Vercel](https://vercel.com), scheduled jobs via free cron triggers hitting authenticated endpoints — the whole thing runs on $0/month.

## Repository layout

```
backend/    Django project — GEE pipelines, REST API, tile serving
  fires/
    gee_fetcher.py       FIRMS fire detection -> DB
    stage_fetcher.py     Crop-stage classification + tiling pipeline
    dashboard.py         Aggregation logic behind the dashboard endpoints
    blob_storage.py      B2/S3-compatible tile storage layer
    gee_assets/          Rice mask + training table builders (run once, offline)
    ml/                  Standalone burn/no-burn classifier (research code)
frontend/   Next.js dashboard
  components/dashboard/  Provincial Summary / District Analytics / Incident Explorer
  components/MapView.tsx Interactive Map (the original single-view map)
render.yaml Backend deploy config (Render Blueprint)
```

## Running it locally

**Backend**
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your GEE service account + OAuth credentials
python manage.py migrate
python manage.py runserver
```

**Frontend**
```bash
cd frontend
npm install
npm run dev
```

Without `DATABASE_URL` set, the backend falls back to local SQLite. Without `B2_*` vars set, tile storage falls back to local disk. Both are meant to make local development work out of the box with zero cloud dependencies beyond your own GEE credentials.

## Populating data

Fire detection is meant to run frequently and cheaply:
```bash
python manage.py fetch_gee_data
```

Crop-stage classification is a heavier pipeline (Earth Engine export → Google Drive download → tiling), typically 15–70 minutes end to end, so it's run on-demand rather than on a tight schedule:
```bash
python manage.py run_stage_fetcher
```

Both are also exposed as authenticated HTTP endpoints (`/api/trigger-fetch/`, `/api/trigger-stage-fetch/`) for scheduler-based triggering in production.

## Why this exists

This started as a final year project, motivated by a very simple observation: the tools to monitor this problem properly already exist and are free to use — NASA and ESA give this satellite data away — but almost nobody outside research contexts is actually stitching it together into something a district government official, journalist, or concerned citizen could actually look at and understand. This is an attempt at that.
