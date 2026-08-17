export type TabKey = 'summary' | 'district' | 'incident' | 'map';

export type ActiveFires = {
  count: number;
  window_days: number;
  trend_pct: number | null;
  trend_window_label: string;
};

export type TrendPoint = { date: string; count: number };

export type SeasonalTrend = {
  start_date: string;
  end_date: string;
  days: TrendPoint[];
};

export type DistrictCount = { district: string; count: number };

export type RecentPoint = {
  point_id: string;
  latitude: number;
  longitude: number;
  fire_date: string;
};

export type DashboardSummary = {
  active_fires: ActiveFires;
  trend: SeasonalTrend;
  district_counts: DistrictCount[];
  top_districts: DistrictCount[];
  recent_points: RecentPoint[];
  at_risk_hectares: number | null;
  dominant_crop_stage: string | null;
  dominant_crop_stage_label: string | null;
  placeholders_note: string | null;
};

export type CropStageSegment = { stage: number; label: string; pct: number; color: string };

export type CropStageDistribution = { date: string; stages: CropStageSegment[] };

export type DistrictSummary = {
  district: string;
  active_fires: ActiveFires;
  trend: SeasonalTrend;
  points: RecentPoint[];
  at_risk_hectares: number | null;
  crop_stage_distribution: CropStageDistribution | null;
};
