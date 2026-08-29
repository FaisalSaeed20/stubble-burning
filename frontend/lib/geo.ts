// Minimal point-in-polygon test (ray casting) supporting the two GeoJSON
// geometry types actually present in punjab_districts.geojson. Avoids
// pulling in a full geometry library (e.g. turf) for this one check.
type Ring = Array<[number, number]>;

function pointInRing(x: number, y: number, ring: Ring): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    const intersects =
      yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

// A GeoJSON polygon's first ring is the outer boundary, any further rings
// are holes to subtract.
function pointInPolygonRings(x: number, y: number, rings: Ring[]): boolean {
  if (!rings.length) return false;
  if (!pointInRing(x, y, rings[0])) return false;
  for (let i = 1; i < rings.length; i++) {
    if (pointInRing(x, y, rings[i])) return false;
  }
  return true;
}

export function pointInGeometry(
  longitude: number,
  latitude: number,
  geometry: { type: string; coordinates: any }
): boolean {
  if (geometry.type === 'Polygon') {
    return pointInPolygonRings(longitude, latitude, geometry.coordinates as Ring[]);
  }
  if (geometry.type === 'MultiPolygon') {
    return (geometry.coordinates as Ring[][]).some((polygon) =>
      pointInPolygonRings(longitude, latitude, polygon)
    );
  }
  return false;
}
