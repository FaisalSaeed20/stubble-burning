import { useEffect, useRef } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet.markercluster/dist/MarkerCluster.css';
import 'leaflet.markercluster/dist/MarkerCluster.Default.css';
import 'leaflet.markercluster';
import dayjs from 'dayjs';

export type ClusterPoint = {
  point_id: string;
  latitude: number;
  longitude: number;
  fire_date: string;
};

const getColorForRecency = (daysAgo: number): string => {
  if (daysAgo <= 1) return '#ff0000';
  if (daysAgo <= 3) return '#ff6600';
  if (daysAgo <= 7) return '#ffcc00';
  return '#999999';
};

const createFireIcon = (color: string): L.Icon => {
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='30' height='30'><circle cx='15' cy='15' r='10' fill='${color}' /></svg>`;
  const svgUrl = `data:image/svg+xml;base64,${btoa(svg)}`;
  return new L.Icon({ iconUrl: svgUrl, iconSize: [30, 30], iconAnchor: [15, 30], popupAnchor: [0, -30] });
};

export default function MarkerClusterLayer<T extends ClusterPoint>({
  firePoints,
  onPointSelect,
}: {
  firePoints: T[];
  onPointSelect?: (point: T) => void;
}) {
  const map = useMap();
  const clusterGroupRef = useRef<L.MarkerClusterGroup | null>(null);

  useEffect(() => {
    if (!map) return;

    const clusterGroup = (L as any).markerClusterGroup({
      maxClusterRadius: 50,
      spiderfyOnMaxZoom: true,
      showCoverageOnHover: false,
      zoomToBoundsOnClick: true,
      iconCreateFunction: function (cluster: any) {
        const markers = cluster.getAllChildMarkers();
        const count = markers.length;

        const colors = markers.map((marker: any) => {
          const firePoint = marker.options.firePoint;
          const daysAgo = dayjs().diff(dayjs(firePoint.fire_date), 'day');
          return getColorForRecency(daysAgo);
        });

        const predominantColor = colors.includes('#ff0000')
          ? '#ff0000'
          : colors.includes('#ff6600')
          ? '#ff6600'
          : colors.includes('#ffcc00')
          ? '#ffcc00'
          : '#999999';

        return L.divIcon({
          html: `<div style="
            background-color: ${predominantColor};
            border: 3px solid white;
            border-radius: 50%;
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            font-size: 14px;
            width: 40px;
            height: 40px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.3);
          ">${count}</div>`,
          className: 'custom-cluster-icon',
          iconSize: [40, 40],
        });
      },
    });

    clusterGroupRef.current = clusterGroup;
    map.addLayer(clusterGroup);

    return () => {
      if (clusterGroupRef.current) {
        map.removeLayer(clusterGroupRef.current);
      }
    };
  }, [map]);

  useEffect(() => {
    if (!clusterGroupRef.current) return;

    clusterGroupRef.current.clearLayers();

    firePoints.forEach((point) => {
      const daysAgo = dayjs().diff(dayjs(point.fire_date), 'day');
      const color = getColorForRecency(daysAgo);
      const icon = createFireIcon(color);

      const marker = L.marker([point.latitude, point.longitude], {
        icon,
        firePoint: point,
      } as any);

      marker.bindPopup(`
        <strong>ID:</strong> ${point.point_id}<br/>
        <strong>Date:</strong> ${new Date(point.fire_date).toLocaleDateString()}<br/>
        <strong>Days Ago:</strong> ${daysAgo}
      `);

      marker.on('click', () => onPointSelect?.(point));
      clusterGroupRef.current?.addLayer(marker);
    });
  }, [firePoints, onPointSelect]);

  return null;
}
