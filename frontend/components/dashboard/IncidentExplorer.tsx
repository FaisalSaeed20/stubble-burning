'use client';

import { useEffect, useState } from 'react';
import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react';
import dayjs from 'dayjs';
import { FireIcon, CalendarDaysIcon, XMarkIcon } from '@heroicons/react/24/solid';
import { API_BASE_URL } from '../../lib/api';
import { getFeatureName } from '../../lib/districtNames';
import FireReport from '../FireReport';

type Incident = { point_id: string; district: string | null; fire_date: string };

type Filters = { district: string; start: string; end: string };

const QUICK_RANGES = [
  { label: 'Last 24h', days: 1 },
  { label: 'Last 7d', days: 7 },
  { label: 'Last 30d', days: 30 },
] as const;

function recencyBadge(fireDate: string): { label: string; className: string } {
  const daysAgo = dayjs().diff(dayjs(fireDate), 'day');
  if (daysAgo <= 1) return { label: 'Last 24h', className: 'bg-red-100 text-red-700' };
  if (daysAgo <= 3) return { label: '1-3 Days', className: 'bg-orange-100 text-orange-700' };
  if (daysAgo <= 7) return { label: '4-7 Days', className: 'bg-yellow-100 text-yellow-700' };
  return { label: 'Older', className: 'bg-gray-100 text-gray-500' };
}

export default function IncidentExplorer() {
  const [districtNames, setDistrictNames] = useState<string[]>([]);
  const [district, setDistrict] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [applied, setApplied] = useState<Filters>({ district: '', start: '', end: '' });
  const [incidents, setIncidents] = useState<Incident[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedPointId, setSelectedPointId] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/districts/`)
      .then((res) => res.json())
      .then((geo: { features: Array<{ properties: Record<string, any> }> }) => {
        const names = Array.from(
          new Set(geo.features.map((f) => getFeatureName(f.properties)).filter(Boolean))
        ).sort();
        setDistrictNames(names);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const params = new URLSearchParams();
    if (applied.district) params.set('district', applied.district);
    if (applied.start) params.set('start', applied.start);
    if (applied.end) params.set('end', applied.end);
    setIncidents(null);
    fetch(`${API_BASE_URL}/api/incidents/?${params.toString()}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        return res.json();
      })
      .then((data) => setIncidents(data.incidents))
      .catch((err) => setError(err.message ?? 'Failed to load incidents'));
  }, [applied]);

  const applyFilters = () => setApplied({ district, start: startDate, end: endDate });
  const resetFilters = () => {
    setDistrict('');
    setStartDate('');
    setEndDate('');
    setApplied({ district: '', start: '', end: '' });
  };
  const applyQuickRange = (days: number) => {
    const end = dayjs().format('YYYY-MM-DD');
    const start = dayjs().subtract(days, 'day').format('YYYY-MM-DD');
    setStartDate(start);
    setEndDate(end);
    setApplied({ district, start, end });
  };

  const dateRangeLabel =
    applied.start && applied.end
      ? `${dayjs(applied.start).format('MMM D, YYYY')} - ${dayjs(applied.end).format('MMM D, YYYY')}`
      : 'All time';

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-xl bg-red-50 p-4 text-sm text-red-700">Couldn't load incidents: {error}</div>
      </div>
    );
  }

  return (
    <div className="min-h-full bg-gradient-to-b from-indigo-50/40 via-gray-50 to-gray-50">
      <div className="mx-auto max-w-7xl px-6 py-6">
        <h2 className="flex items-center gap-2 text-2xl font-bold text-gray-900">
          <FireIcon className="h-6 w-6 text-red-600" />
          Fire Incident Explorer
        </h2>
        <p className="mt-1 text-sm text-gray-500">Browse and analyze individual fire incidents detected across Punjab</p>

        <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-4">
          <div className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-100 lg:col-span-1">
            <h3 className="mb-4 text-sm font-semibold text-gray-700">Filters</h3>

            <label className="block text-xs font-medium text-gray-500">District</label>
            <select
              value={district}
              onChange={(e) => setDistrict(e.target.value)}
              className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700"
            >
              <option value="">All Punjab</option>
              {districtNames.map((name) => (
                <option key={name} value={name}>
                  {name} District
                </option>
              ))}
            </select>

            <label className="mt-4 block text-xs font-medium text-gray-500">Start Date</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700"
            />

            <label className="mt-4 block text-xs font-medium text-gray-500">End Date</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700"
            />

            <p className="mt-4 text-xs font-medium text-gray-500">Quick Dates</p>
            <div className="mt-1 flex flex-wrap gap-2">
              {QUICK_RANGES.map((range) => (
                <button
                  key={range.label}
                  onClick={() => applyQuickRange(range.days)}
                  className="rounded-full border border-gray-200 px-3 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
                >
                  {range.label}
                </button>
              ))}
            </div>

            <div className="mt-4 flex gap-2">
              <button
                onClick={resetFilters}
                className="flex-1 rounded-lg border border-gray-200 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50"
              >
                Reset
              </button>
              <button
                onClick={applyFilters}
                className="flex-1 rounded-lg bg-blue-600 py-2 text-sm font-medium text-white hover:bg-blue-700"
              >
                Apply
              </button>
            </div>
          </div>

          <div className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-100 lg:col-span-3">
            <div className="flex flex-wrap items-center gap-6 border-b border-gray-100 pb-4">
              <div className="flex items-center gap-2">
                <FireIcon className="h-5 w-5 text-red-500" />
                <span className="text-sm text-gray-500">Total Incidents</span>
                <span className="text-lg font-bold text-gray-900">{incidents ? incidents.length : '—'}</span>
              </div>
              <div className="flex items-center gap-2">
                <CalendarDaysIcon className="h-5 w-5 text-blue-500" />
                <span className="text-sm text-gray-500">Date Range</span>
                <span className="text-sm font-semibold text-gray-800">{dateRangeLabel}</span>
              </div>
            </div>

            {!incidents ? (
              <div className="py-10 text-center text-sm text-gray-400">Loading incidents…</div>
            ) : incidents.length === 0 ? (
              <div className="py-10 text-center text-sm text-gray-400">No incidents match these filters.</div>
            ) : (
              <div className="max-h-[600px] overflow-auto">
                <table className="mt-2 w-full text-left text-sm">
                  <thead>
                    <tr className="text-xs uppercase tracking-wide text-gray-400">
                      <th className="py-2 pr-4">Point ID</th>
                      <th className="py-2 pr-4">District</th>
                      <th className="py-2 pr-4">Fire Date</th>
                      <th className="py-2 pr-4">Recency</th>
                      <th className="py-2 pr-4">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {incidents.map((incident) => {
                      const recency = recencyBadge(incident.fire_date);
                      return (
                        <tr key={incident.point_id} className="border-t border-gray-50">
                          <td className="py-3 pr-4 font-medium text-gray-800">{incident.point_id}</td>
                          <td className="py-3 pr-4 text-gray-600">
                            {incident.district ? `${incident.district} District` : 'Unclassified'}
                          </td>
                          <td className="py-3 pr-4 text-gray-600">{dayjs(incident.fire_date).format('MMM D, YYYY')}</td>
                          <td className="py-3 pr-4">
                            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${recency.className}`}>
                              {recency.label}
                            </span>
                          </td>
                          <td className="py-3 pr-4">
                            <button
                              onClick={() => setSelectedPointId(incident.point_id)}
                              className="text-sm font-medium text-blue-600 hover:underline"
                            >
                              View Details
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>

      <Dialog open={selectedPointId != null} onClose={() => setSelectedPointId(null)} className="relative z-50">
        <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <DialogPanel className="relative w-full max-w-lg">
            <button
              onClick={() => setSelectedPointId(null)}
              className="absolute -right-2 -top-2 z-10 flex h-8 w-8 items-center justify-center rounded-full bg-white shadow-md"
            >
              <XMarkIcon className="h-5 w-5 text-gray-500" />
            </button>
            <DialogTitle className="sr-only">Fire incident details</DialogTitle>
            {selectedPointId && <FireReport pointId={selectedPointId} />}
          </DialogPanel>
        </div>
      </Dialog>
    </div>
  );
}
