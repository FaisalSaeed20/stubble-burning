'use client';

import { useEffect, useState } from 'react';
import { FireIcon, MapPinIcon, SparklesIcon } from '@heroicons/react/24/solid';
import { API_BASE_URL } from '../../lib/api';
import StatCard from './StatCard';
import TopDistrictsChart from './TopDistrictsChart';
import SeasonalTrendChart from './SeasonalTrendChart';
import RiskMapPanel from './RiskMapPanel';
import type { DashboardSummary } from './types';

export default function ProvincialSummary() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/dashboard-summary/?days=30`)
      .then((res) => {
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        return res.json();
      })
      .then(setSummary)
      .catch((err) => setError(err.message ?? 'Failed to load dashboard summary'));
  }, []);

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-xl bg-red-50 p-4 text-sm text-red-700">
          Couldn't load the provincial summary: {error}
        </div>
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-400">
        Loading provincial overview…
      </div>
    );
  }

  return (
    <div className="min-h-full bg-gradient-to-b from-indigo-50/40 via-gray-50 to-gray-50">
      <div className="mx-auto max-w-7xl px-6 py-6">
        <h2 className="text-2xl font-bold text-gray-900">Provincial Strategic Overview</h2>
        <p className="mt-1 text-sm text-gray-500">High-level insights for executive decision-making</p>

        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatCard
            icon={FireIcon}
            iconBgClassName="bg-red-100 text-red-600"
            label="Total Active Fires"
            sublabel={`Across all ${summary.district_counts.length} districts`}
            value={String(summary.active_fires.count)}
            trend={
              summary.active_fires.trend_pct != null
                ? { pct: summary.active_fires.trend_pct, label: summary.active_fires.trend_window_label }
                : null
            }
          />
          <StatCard
            icon={MapPinIcon}
            iconBgClassName="bg-orange-100 text-orange-600"
            label="At-Risk Hectares"
            value={
              summary.at_risk_hectares != null
                ? summary.at_risk_hectares.toLocaleString(undefined, { maximumFractionDigits: 2 })
                : '—'
            }
            sublabel={summary.at_risk_hectares != null ? 'Punjab-wide rice cropland' : undefined}
            isPlaceholder={summary.at_risk_hectares == null}
            placeholderNote="Run `manage.py build_rice_mask` to compute this"
          />
          <StatCard
            icon={SparklesIcon}
            iconBgClassName="bg-purple-100 text-purple-600"
            label="Dominant Crop Stage"
            value={summary.dominant_crop_stage ?? '—'}
            sublabel={summary.dominant_crop_stage_label ?? undefined}
            isPlaceholder={summary.dominant_crop_stage == null}
            placeholderNote="Computed automatically next time the stage-fetch pipeline runs"
          />
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
          <RiskMapPanel points={summary.recent_points} districtCounts={summary.district_counts} />
          <div className="flex flex-col gap-4 lg:col-span-1">
            <TopDistrictsChart data={summary.top_districts} />
            <SeasonalTrendChart data={summary.trend.days} />
          </div>
        </div>
      </div>
    </div>
  );
}
