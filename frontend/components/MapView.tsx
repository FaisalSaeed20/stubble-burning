'use client';

import { useEffect, useMemo, useState, useRef } from 'react';
import { MapContainer, TileLayer, useMapEvents, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import icon from 'leaflet/dist/images/marker-icon.png';
import iconShadow from 'leaflet/dist/images/marker-shadow.png';
import Sidebar from './Sidebar';
import FireReport from './FireReport';
import { API_BASE_URL } from '../lib/api';
import MarkerClusterLayer from './MarkerClusterLayer';
import { norm, getFeatureName } from '../lib/districtNames';
import { pointInGeometry } from '../lib/geo';
// Chart.js
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  LineElement,
  PointElement,
  LinearScale,
  Title,
  CategoryScale,
  Legend,
  Tooltip,
} from 'chart.js';
ChartJS.register(LineElement, PointElement, LinearScale, Title, CategoryScale, Legend, Tooltip);



// --- Chart vertical line plugin ---
const fireLinePlugin = {
  id: 'fireLine',
  afterDraw: (chart: any, _args: any, options: { fireDate?: string }) => {
    const { fireDate } = options;
    if (!fireDate) return;

    const { ctx, chartArea: { top, bottom }, scales: { x } } = chart;
    const fireDateOnly = fireDate.substring(0, 10);
    const fireDateIndex = chart.data.labels?.findIndex((label: string) => label >= fireDateOnly);
    if (fireDateIndex === undefined || fireDateIndex < 0) return;

    const xCoord = x.getPixelForValue(fireDateIndex);
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(xCoord, top);
    ctx.lineTo(xCoord, bottom);
    ctx.lineWidth = 2;
    ctx.strokeStyle = 'rgba(255, 0, 0, 0.7)';
    ctx.stroke();
    ctx.restore();
  },
};

// --- Leaflet defaults ---
let DefaultIcon = L.icon({
  iconUrl: (icon as any).src || (icon as any),
  shadowUrl: (iconShadow as any).src || (iconShadow as any),
  iconAnchor: [12, 41],
});
(L.Marker.prototype as any).options.icon = DefaultIcon;

// --- Types ---
type FirePoint = {
  point_id: string;
  latitude: number;
  longitude: number;
  fire_date: string;
  image_date: string[];
  NDVI: (number | null)[];
  NDWI: (number | null)[];
  NBR: (number | null)[];
  NDRE: (number | null)[];
  VV: (number | null)[];
  VH: (number | null)[];
};
type MetricKey = 'NDVI' | 'NDWI' | 'NBR' | 'NDRE' | 'VV' | 'VH';

type StageData = {
  dates: string[];
  years: Record<string, string[]>;
  latest: string | null;
};

const COLORS: Record<MetricKey, string> = {
  NDVI: '#16a34a',
  NDWI: '#2563eb',
  NBR: '#f97316',
  NDRE: '#9333ea',
  VV: '#dc2626',
  VH: '#78350f',
};
const S2_METRICS: MetricKey[] = ['NDVI', 'NDWI', 'NBR', 'NDRE'];
const S1_METRICS: MetricKey[] = ['VV', 'VH'];

const generateChartData = (point: FirePoint | null, metrics: MetricKey[]) => {
  const labels = point?.image_date ?? [];
  const datasets = metrics
    .filter((k) => Array.isArray(point?.[k]) && point?.[k]?.some((v) => typeof v === 'number'))
    .map((k) => ({
      label: k,
      data: (point?.[k] as (number | null)[]) ?? [],
      borderColor: COLORS[k],
      backgroundColor: COLORS[k] + '33',
      fill: false,
      tension: 0.2,
      spanGaps: true,
    }));
  return { labels, datasets };
};

// ---------- District support ----------
type DistrictGeo = {
  type: 'FeatureCollection';
  features: Array<{ type: 'Feature'; properties: Record<string, any>; geometry: any }>;
};

function ZoomTracker({ onZoom }: { onZoom: (z: number) => void }) {
  useMapEvents({ zoomend: (e) => onZoom(e.target.getZoom()) });
  return null;
}

function DistrictFit({
  selected,
  geo,
  showOutline = true,
}: {
  selected: string;
  geo: DistrictGeo | null;
  showOutline?: boolean;
}) {
  const map = useMap();
  const outlineRef = useRef<L.GeoJSON | null>(null);

  useEffect(() => {
    if (!geo) return;

    const features = selected
      ? geo.features.filter((f) => norm(getFeatureName(f.properties)) === norm(selected))
      : geo.features;

    if (!features.length) return;

    const tmp = L.geoJSON(features as any);
    const bounds = tmp.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [24, 24] });

    if (showOutline) {
      if (outlineRef.current) {
        map.removeLayer(outlineRef.current);
        outlineRef.current = null;
      }
      if (selected) {
        const layer = L.geoJSON(features as any, { style: { color: '#2563eb', weight: 2, fillOpacity: 0.05 } });
        layer.addTo(map);
        layer.bringToFront();
        outlineRef.current = layer;
      }
    }

    return () => {
      if (outlineRef.current) {
        map.removeLayer(outlineRef.current);
        outlineRef.current = null;
      }
    };
  }, [selected, geo, map, showOutline]);

  return null;
}

export default function MapView() {
  const [firePoints, setFirePoints] = useState<FirePoint[]>([]);
  const [zoomLevel, setZoomLevel] = useState(6);
  const [selectedPoint, setSelectedPoint] = useState<FirePoint | null>(null);
  const [startDate, setStartDate] = useState<string>('');
  const [endDate, setEndDate] = useState<string>('');

  // District state
  const [districts, setDistricts] = useState<string[]>([]);
  const [selectedDistrict, setSelectedDistrict] = useState<string>('');
  const [districtGeo, setDistrictGeo] = useState<DistrictGeo | null>(null);

  // NEW: Stage layer state
  const [stageData, setStageData] = useState<StageData | null>(null);
  const [showCurrentStage, setShowCurrentStage] = useState<boolean>(false);
  const [showArchive, setShowArchive] = useState<boolean>(false);
  const [selectedArchiveDate, setSelectedArchiveDate] = useState<string>('');

  // --- NEW HEATMAP STATE ---
  const [showCO, setShowCO] = useState(false);
  const [showNO2, setShowNO2] = useState(false);
  const [showAAI, setShowAAI] = useState(false);
  // --- END NEW STATE ---

  const fetchFireData = async (start: string, end: string) => {
    try {
      const url = new URL(`${API_BASE_URL}/api/fire-timeseries/`);
      url.searchParams.append('region', 'Pakistani Punjab');
      url.searchParams.append('start', start);
      url.searchParams.append('end', end);
      const res = await fetch(url.toString());
      const data = await res.json();
      if (Array.isArray(data)) setFirePoints(data);
      else console.error('🔥 Fire data is not an array:', data);
    } catch (err) {
      console.error('❌ Failed to fetch fire data:', err);
    }
  };

  // NEW: Fetch stage dates
  const fetchStageData = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/stage-dates/`);
      if (!res.ok) {
        console.warn('Stage dates API not available yet');
        return;
      }
      const data: StageData = await res.json();
      setStageData(data);
      
      // Set initial archive date to the latest if available
      if (data.dates.length > 0 && !selectedArchiveDate) {
        setSelectedArchiveDate(data.dates[data.dates.length - 1]);
      }
    } catch (err) {
      console.warn('Failed to fetch stage dates:', err);
    }
  };

  useEffect(() => {
    fetchFireData(startDate, endDate);
    fetchStageData();
  }, []);

  // Load district polygons from Django API
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/districts/`);
        if (!res.ok) {
          console.warn('Districts API not available yet');
          return;
        }
        const geo: DistrictGeo = await res.json();
        setDistrictGeo(geo);

        const names = Array.from(
          new Set(
            geo.features
              .map((f) => getFeatureName(f.properties))
              .filter(Boolean)
          )
        ).sort((a, b) => a.localeCompare(b));
        setDistricts(names);
      } catch (e) {
        console.warn('Failed to load districts from API:', e);
      }
    })();
  }, []);

  const s2ChartData = useMemo(() => generateChartData(selectedPoint, S2_METRICS), [selectedPoint]);
  const s1ChartData = useMemo(() => generateChartData(selectedPoint, S1_METRICS), [selectedPoint]);

  // When a district is selected, restrict the map to only that district's
  // fire points -- keeps the full time-series data each point already
  // carries (needed for the chart panels), just filtered client-side by
  // membership in the selected district's polygon rather than re-fetching
  // a lighter per-district endpoint that doesn't carry that data.
  const visibleFirePoints = useMemo(() => {
    if (!selectedDistrict || !districtGeo) return firePoints;
    const features = districtGeo.features.filter(
      (f) => norm(getFeatureName(f.properties)) === norm(selectedDistrict)
    );
    if (!features.length) return firePoints;
    return firePoints.filter((p) =>
      features.some((f) => pointInGeometry(p.longitude, p.latitude, f.geometry))
    );
  }, [firePoints, selectedDistrict, districtGeo]);

  // Determine which stage date to show
  const activeStageDate = showCurrentStage && stageData?.latest 
    ? stageData.latest 
    : showArchive 
    ? selectedArchiveDate 
    : null;

  return (
    <div className="flex h-full w-full">
      <Sidebar
        onApply={(start, end) => {
          setStartDate(start);
          setEndDate(end);
          fetchFireData(start, end);
        }}
        onReset={() => {
          setStartDate('');
          setEndDate('');
          fetchFireData('', '');
        }}
        districts={districts}
        selectedDistrict={selectedDistrict}
        onDistrictChange={(name) => setSelectedDistrict(name)}
        
        // NEW: Stage control props
        showCurrentStage={showCurrentStage}
        onCurrentStageToggle={(show) => {
          setShowCurrentStage(show);
          if (show) setShowArchive(false); // Only one at a time
        }}
        showArchive={showArchive}
        onArchiveToggle={(show) => {
          setShowArchive(show);
          if (show) setShowCurrentStage(false); // Only one at a time
        }}
        selectedArchiveDate={selectedArchiveDate}
        onArchiveDateChange={setSelectedArchiveDate}
        stageData={stageData}

        // --- NEW HEATMAP PROPS ---
      showCO={showCO}
      onShowCOToggle={setShowCO}
      showNO2={showNO2}
      onShowNO2Toggle={setShowNO2}
      showAAI={showAAI}
      onShowAAIToggle={setShowAAI}
      />

      <div className="relative flex-grow">
        <MapContainer
          center={[30.3753, 71.5249]}
          zoom={6}
          minZoom={5}
          style={{ height: '100%', width: '100%' }}
        >
          <ZoomTracker onZoom={(z) => setZoomLevel(z)} />

          {/* Fit & outline district when selected */}
          <DistrictFit selected={selectedDistrict} geo={districtGeo} showOutline={true} />

          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="&copy; OpenStreetMap contributors"
          />

          {/* Rice crop overlay */}
          <TileLayer 
            url={`${API_BASE_URL}/api/tiles/{z}/{x}/{y}.png`}
            opacity={0.6} 
            zIndex={1000} 
          />

          {/* NEW: Stage classification overlay */}
          {activeStageDate && (
            <TileLayer
              key={activeStageDate} // Force re-render when date changes
              url={`${API_BASE_URL}/api/stage-tiles/${activeStageDate}/{z}/{x}/{y}.png`}
              opacity={0.7}
              zIndex={1001}
            />
          )}

          {/* Clustered Fire Points */}
          <MarkerClusterLayer firePoints={visibleFirePoints} onPointSelect={setSelectedPoint} />
        {/* --- NEW HEATMAP LAYERS --- */}
          {showCO && (
            <TileLayer
              key="co-layer"
              url={`${API_BASE_URL}/api/heatmap-tiles/co/{z}/{x}/{y}.png`}
              opacity={0.7}
              zIndex={1002}
            />
          )}
          {showNO2 && (
            <TileLayer
              key="no2-layer"
              url={`${API_BASE_URL}/api/heatmap-tiles/no2/{z}/{x}/{y}.png`}
              opacity={0.7}
              zIndex={1002}
            />
          )}
          {showAAI && (
            <TileLayer
              key="aai-layer"
              url={`${API_BASE_URL}/api/heatmap-tiles/aai/{z}/{x}/{y}.png`}
              opacity={0.7}
              zIndex={1002}
            />
          )}
          {/* --- END NEW LAYERS --- */}
        
        </MapContainer>

        {/* Active Stage Info Panel */}
        {activeStageDate && (
          <div className="absolute top-4 left-4 bg-white rounded-lg shadow-lg p-3 z-[1002] min-w-[200px]">
            <div className="flex items-center justify-between">
              <h4 className="font-semibold text-sm">🌾 Rice Growth Stage</h4>
              <button
                onClick={() => {
                  setShowCurrentStage(false);
                  setShowArchive(false);
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                ✕
              </button>
            </div>
            <p className="text-xs text-gray-600 mt-1">
              {showCurrentStage ? 'Current' : 'Archive'}: {
                `${activeStageDate.slice(0, 4)}-${activeStageDate.slice(4, 6)}-${activeStageDate.slice(6, 8)}`
              }
            </p>
          </div>
        )}

        {/* Sentinel-2 Chart Panel */}
        {selectedPoint && s2ChartData.datasets.length > 0 && (
          <div className="absolute top-4 right-4 w-[500px] bg-white rounded-xl shadow-lg p-4 z-[1001]">
            <button
              className="absolute top-2 right-3 text-red-500 font-bold"
              onClick={() => setSelectedPoint(null)}
            >
              ✕
            </button>
            <h3 className="text-md font-semibold text-center mb-2">
              Sentinel-2 Optical Indices - {selectedPoint.point_id}
            </h3>
            <Line
              data={s2ChartData}
              options={{
                responsive: true,
                plugins: { legend: { position: 'bottom' }, fireLine: { fireDate: selectedPoint?.fire_date } } as any,
                scales: { y: { title: { display: true, text: 'Index Value' } } },
              }}
              plugins={[fireLinePlugin as any]}
            />
          </div>
        )}
        {selectedPoint && (
  <div className="absolute top-[100px] left-4 bg-white rounded-lg shadow-lg p-4 z-[1002] w-[280px]">
    <h3 className="font-semibold text-md mb-2">🔥 Fire Point Info</h3>
    <p><strong>ID:</strong> {selectedPoint.point_id}</p>
    <p><strong>Date:</strong> {new Date(selectedPoint.fire_date).toLocaleDateString()}</p>

    {/* Fire Report Button */}
    <FireReport pointId={selectedPoint.point_id} />
  </div>
)}

 

        {/* Sentinel-1 Chart Panel */}
        {selectedPoint && s1ChartData.datasets.length > 0 && (
          <div className="absolute bottom-4 right-4 w-[500px] bg-white rounded-xl shadow-lg p-4 z-[1001]">
            <button
              className="absolute top-2 right-3 text-red-500 font-bold"
              onClick={() => setSelectedPoint(null)}
            >
              ✕
            </button>
            <h3 className="text-md font-semibold text-center mb-2">
              Sentinel-1 Radar Backscatter (dB) - {selectedPoint.point_id}
            </h3>
            <Line
              data={s1ChartData}
              options={{
                responsive: true,
                plugins: { legend: { position: 'bottom' }, fireLine: { fireDate: selectedPoint?.fire_date } } as any,
                scales: { y: { title: { display: true, text: 'Decibels (dB)' } } },
              }}
              plugins={[fireLinePlugin as any]}
            />
          </div>
        )}

        {/* Fire Recency Legend */}
        <div className="absolute bottom-4 left-4 bg-white shadow-md rounded-lg p-4 z-[1001] text-sm">
          <p className="font-semibold mb-2">🔥 Fire Recency Legend</p>
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="w-4 h-4 rounded-full" style={{ backgroundColor: '#ff0000' }}></span>
              <span>Last 24h</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-4 h-4 rounded-full" style={{ backgroundColor: '#ff6600' }}></span>
              <span>1–3 days ago</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-4 h-4 rounded-full" style={{ backgroundColor: '#ffcc00' }}></span>
              <span>4–7 days ago</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-4 h-4 rounded-full" style={{ backgroundColor: '#999999' }}></span>
              <span>Older</span>
            </div>
          </div>
          <div className="mt-3 pt-2 border-t">
            <p className="text-xs text-gray-600">
              📊 {selectedDistrict ? `${selectedDistrict} Fire Points` : 'Total Fire Points'}: {visibleFirePoints.length}
            </p>
          </div>
        </div>

          {/* --- NEW HEATMAP LEGENDS --- */}
        <div className="absolute bottom-4 left-52 space-y-2 z-[1001]">
          {showCO && (
            <HeatmapLegend title="CO (mol/m^2)" min="0.0" max="0.05" />
          )}
          {showNO2 && (
            <HeatmapLegend title="NO2 (mol/m^2)" min="0.0" max="0.0002" />
          )}
          {showAAI && (
            <HeatmapLegend title="AAI (Index)" min="-1.0" max="2.0" />
          )}
        </div>
        {/* --- END NEW LEGENDS --- */}

      </div>
    </div>
  );
}


const HeatmapLegend = ({ title, min, max }: { title: string, min: string, max: string }) => (
  <div className="p-2 bg-white rounded shadow text-xs">
    <p className="font-semibold text-center mb-1">{title}</p>
    <div
      className="w-full h-3 border border-gray-300"
      style={{
        background: 'linear-gradient(to right, black, blue, purple, cyan, green, yellow, red)',
      }}
    />
    <div className="flex justify-between mt-1">
      <span>{min}</span>
      <span>{max}</span>
    </div>
  </div>
);