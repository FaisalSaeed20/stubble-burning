'use client';

import { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, GeoJSON, useMap } from 'react-leaflet';
import L from 'leaflet';
import { ArrowTrendingUpIcon, ArrowTrendingDownIcon } from '@heroicons/react/24/solid';
import { API_BASE_URL } from '../../lib/api';
import { getFeatureName } from '../../lib/districtNames';
import MarkerClusterLayer from '../MarkerClusterLayer';
import SeasonalTrendChart from './SeasonalTrendChart';
import type { DistrictSummary } from './types';

type DistrictGeo = {
  type: 'FeatureCollection';
  features: Array<{ type: 'Feature'; properties: Record<string, any>; geometry: any }>;
};

const HEATMAP_LAYERS = [
  { key: 'co', label: 'CO Layer' },
  { key: 'no2', label: 'NO₂ Layer' },
  { key: 'aai', label: 'AAI Layer' },
] as const;

function FitToFeature({ feature }: { feature: any }) {
  const map = useMap();
  useEffect(() => {
    if (!feature) return;
    const bounds = L.geoJSON(feature).getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [24, 24] });
  }, [feature, map]);
  return null;
}

export default function DistrictAnalytics() {
  const [districtGeo, setDistrictGeo] = useState<DistrictGeo | null>(null);
  const [districtNames, setDistrictNames] = useState<string[]>([]);
  const [selectedDistrict, setSelectedDistrict] = useState<string>('');
  const [summary, setSummary] = useState<DistrictSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asOfDate, setAsOfDate] = useState<string>('');
  const [heatmapLayer, setHeatmapLayer] = useState<(typeof HEATMAP_LAYERS)[number]['key'] | null>(null);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/districts/`)
      .then((res) => res.json())
      .then((geo: DistrictGeo) => {
        setDistrictGeo(geo);
        const names = Array.from(new Set(geo.features.map((f) => getFeatureName(f.properties)).filter(Boolean))).sort();
        setDistrictNames(names);
        const defaultDistrict = names.find((n) => n.toLowerCase() === 'hafizabad') || names[0] || '';
        setSelectedDistrict(defaultDistrict);
      })
      .catch((err) => setError(err.message ?? 'Failed to load districts'));
  }, []);

  useEffect(() => {
    if (!selectedDistrict) return;
    setSummary(null);
    fetch(`${API_BASE_URL}/api/district-summary/?district=${encodeURIComponent(selectedDistrict)}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        return res.json();
      })
      .then(setSummary)
      .catch((err) => setError(err.message ?? 'Failed to load district summary'));
  }, [selectedDistrict]);

  const filteredPoints = useMemo(() => {
    if (!summary) return [];
    if (!asOfDate) return summary.points;
    return summary.points.filter((p) => p.fire_date.slice(0, 10) <= asOfDate);
  }, [summary, asOfDate]);

  const selectedFeature = useMemo(() => {
    if (!districtGeo || !selectedDistrict) return null;
    return districtGeo.features.find((f) => getFeatureName(f.properties) === selectedDistrict) || null;
  }, [districtGeo, selectedDistrict]);

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-xl bg-red-50 p-4 text-sm text-red-700">Couldn't load district analytics: {error}</div>
      </div>
    );
  }

  return (
    <div className="min-h-full bg-gradient-to-b from-indigo-50/40 via-gray-50 to-gray-50">
      <div className="mx-auto max-w-7xl px-6 py-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">District Tactical Analytics</h2>
            <p className="mt-1 text-sm text-gray-500">Detailed analysis for district-level management</p>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-500">Select District:</label>
            <select
              value={selectedDistrict}
              onChange={(e) => setSelectedDistrict(e.target.value)}
              className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-700"
            >
              {districtNames.map((name) => (
                <option key={name} value={name}>
                  {name} District
                </option>
              ))}
            </select>
          </div>
        </div>

        {!summary ? (
          <div className="mt-10 text-center text-sm text-gray-400">Loading district analytics…</div>
        ) : (
          <>
            <div className="mt-6 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-100">
              <div className="flex items-start justify-between">
                <div>
                  <span className="text-sm text-gray-500">
                    {summary.district} District — {summary.active_fires.window_days}-Day Fire Count
                  </span>
                  <div className="mt-2 text-3xl font-bold text-gray-900">{summary.active_fires.count}</div>
                  <p className="mt-1 text-sm text-gray-400">
                    {summary.at_risk_hectares != null
                      ? `At-Risk Area: ${summary.at_risk_hectares.toLocaleString(undefined, { maximumFractionDigits: 2 })} ha`
                      : 'At-Risk Area: Not yet available'}
                  </p>
                </div>
                {summary.active_fires.trend_pct != null && (
                  <span
                    className={`flex h-10 w-10 items-center justify-center rounded-full ${
                      summary.active_fires.trend_pct > 0 ? 'bg-red-100 text-red-600' : 'bg-green-100 text-green-600'
                    }`}
                  >
                    {summary.active_fires.trend_pct > 0 ? (
                      <ArrowTrendingUpIcon className="h-5 w-5" />
                    ) : (
                      <ArrowTrendingDownIcon className="h-5 w-5" />
                    )}
                  </span>
                )}
              </div>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-gray-100">
                <h3 className="mb-3 text-sm font-semibold text-gray-700">Crop Stage Distribution</h3>
                {summary.crop_stage_distribution ? (
                  <div>
                    <div className="flex h-6 w-full overflow-hidden rounded-full bg-gray-100">
                      {summary.crop_stage_distribution.stages
                        .filter((s) => s.pct > 0)
                        .map((s) => (
                          <div
                            key={s.stage}
                            style={{ width: `${s.pct}%`, backgroundColor: s.color }}
                            title={`${s.label}: ${s.pct}%`}
                          />
                        ))}
                    </div>
                    <div className="mt-3 flex flex-wrap gap-3 text-xs text-gray-500">
                      {summary.crop_stage_distribution.stages
                        .filter((s) => s.pct > 0)
                        .map((s) => (
                          <span key={s.stage} className="flex items-center gap-1">
                            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: s.color }} />
                            Stage {s.stage} ({s.pct}%)
                          </span>
                        ))}
                    </div>
                  </div>
                ) : (
                  <p className="text-sm italic text-gray-300">Not yet available for this district</p>
                )}
              </div>
              <SeasonalTrendChart data={summary.trend.days} title="90-Day Fire Trend" />
            </div>

            <div className="mt-4 rounded-2xl bg-white p-4 shadow-sm ring-1 ring-gray-100">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-gray-700">District Map View</h3>
                <input
                  type="date"
                  value={asOfDate}
                  onChange={(e) => setAsOfDate(e.target.value)}
                  className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600"
                />
              </div>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
                <div className="h-[420px] w-full overflow-hidden rounded-xl lg:col-span-3">
                  <MapContainer center={[32.0713, 73.6913]} zoom={9} style={{ height: '100%', width: '100%' }}>
                    <TileLayer
                      attribution="&copy; OpenStreetMap contributors"
                      url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    />
                    {selectedFeature && (
                      <>
                        <GeoJSON
                          key={selectedDistrict}
                          data={selectedFeature as any}
                          style={{ color: '#0ea5e9', weight: 2, fillColor: '#22d3ee', fillOpacity: 0.15 }}
                        />
                        <FitToFeature feature={selectedFeature} />
                      </>
                    )}
                    <MarkerClusterLayer firePoints={filteredPoints} />
                    {heatmapLayer && (
                      <TileLayer
                        key={heatmapLayer}
                        url={`${API_BASE_URL}/api/heatmap-tiles/${heatmapLayer}/{z}/{x}/{y}.png`}
                        opacity={0.6}
                      />
                    )}
                  </MapContainer>
                </div>
                <div className="rounded-xl bg-gray-50 p-4">
                  <h4 className="text-sm font-semibold text-gray-700">Atmospheric Layer Controls</h4>
                  <p className="mt-1 text-xs text-gray-400">Select atmospheric layer to display on map:</p>
                  <div className="mt-3 flex flex-col gap-2">
                    {HEATMAP_LAYERS.map((layer) => (
                      <button
                        key={layer.key}
                        onClick={() => setHeatmapLayer(heatmapLayer === layer.key ? null : layer.key)}
                        className={`rounded-full px-3 py-1.5 text-xs font-medium ${
                          heatmapLayer === layer.key ? 'bg-blue-600 text-white' : 'border border-gray-200 text-gray-600'
                        }`}
                      >
                        {layer.label}
                      </button>
                    ))}
                  </div>
                  <p className="mt-4 text-xs text-gray-400">Active Layer: {heatmapLayer ? heatmapLayer.toUpperCase() : 'None'}</p>
                  <p className="mt-3 text-xs text-gray-400">7-day rolling average, live from Earth Engine.</p>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
