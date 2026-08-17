'use client';

import { useEffect, useState } from 'react';
import { MapContainer, TileLayer, GeoJSON } from 'react-leaflet';
import MarkerClusterLayer from '../MarkerClusterLayer';
import { norm, getFeatureName } from '../../lib/districtNames';
import { API_BASE_URL } from '../../lib/api';
import type { DistrictCount, RecentPoint } from './types';

type DistrictGeo = {
  type: 'FeatureCollection';
  features: Array<{ type: 'Feature'; properties: Record<string, any>; geometry: any }>;
};

type StageDates = { dates: string[]; years: Record<string, string[]>; latest: string | null };

function bucketColor(count: number): string {
  if (count === 0) return '#e5e7eb'; // gray - not in current ingestion scope, not "confirmed low risk"
  if (count < 10) return '#eda100'; // yellow
  if (count < 50) return '#f97316'; // orange
  return '#dc2626'; // red
}

export default function RiskMapPanel({
  points,
  districtCounts,
}: {
  points: RecentPoint[];
  districtCounts: DistrictCount[];
}) {
  const [mode, setMode] = useState<'clusters' | 'stages'>('clusters');
  const [districtGeo, setDistrictGeo] = useState<DistrictGeo | null>(null);
  const [stageData, setStageData] = useState<StageDates | null>(null);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/districts/`)
      .then((res) => res.json())
      .then(setDistrictGeo)
      .catch((err) => console.error('Failed to load district boundaries:', err));
  }, []);

  useEffect(() => {
    if (mode !== 'stages' || stageData) return;
    fetch(`${API_BASE_URL}/api/stage-dates/`)
      .then((res) => res.json())
      .then(setStageData)
      .catch((err) => console.error('Failed to load stage dates:', err));
  }, [mode, stageData]);

  const countByDistrict = new Map(districtCounts.map((row) => [norm(row.district), row.count]));

  const districtStyle = (feature: any) => {
    const count = countByDistrict.get(norm(getFeatureName(feature.properties))) ?? 0;
    return { fillColor: bucketColor(count), fillOpacity: 0.45, weight: 1, color: '#9ca3af' };
  };

  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-gray-100 lg:col-span-2">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">Punjab District Risk Map</h3>
        <div className="flex gap-2">
          <button
            onClick={() => setMode('clusters')}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              mode === 'clusters' ? 'bg-blue-600 text-white' : 'border border-gray-200 text-gray-600'
            }`}
          >
            Fire Clusters
          </button>
          <button
            onClick={() => setMode('stages')}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              mode === 'stages' ? 'bg-blue-600 text-white' : 'border border-gray-200 text-gray-600'
            }`}
          >
            Crop Stages
          </button>
        </div>
      </div>

      <div className="h-[420px] w-full overflow-hidden rounded-xl">
        <MapContainer center={[30.3753, 71.5249]} zoom={6} minZoom={5} style={{ height: '100%', width: '100%' }}>
          <TileLayer
            attribution="&copy; OpenStreetMap contributors"
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {districtGeo && <GeoJSON data={districtGeo as any} style={districtStyle as any} />}
          {mode === 'clusters' && <MarkerClusterLayer firePoints={points} />}
          {mode === 'stages' && stageData?.latest && (
            <TileLayer
              key={stageData.latest}
              url={`${API_BASE_URL}/api/stage-tiles/${stageData.latest}/{z}/{x}/{y}.png`}
              opacity={0.7}
            />
          )}
        </MapContainer>
      </div>
      {mode === 'stages' && stageData && !stageData.latest && (
        <p className="mt-2 text-xs text-gray-400">No crop-stage imagery available yet.</p>
      )}
    </div>
  );
}
