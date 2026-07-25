'use client';

import dayjs from 'dayjs';
import { useState, useEffect } from 'react';

type StageData = {
  dates: string[];
  years: Record<string, string[]>;
  latest: string | null;
};

type Props = {
  onApply: (start: string, end: string) => void;
  onReset: () => void;

  // District controls
  districts: string[];
  selectedDistrict: string;
  onDistrictChange: (name: string) => void;

  // NEW: Stage controls
  showCurrentStage: boolean;
  onCurrentStageToggle: (show: boolean) => void;
  showArchive: boolean;
  onArchiveToggle: (show: boolean) => void;
  selectedArchiveDate: string;
  onArchiveDateChange: (date: string) => void;
  stageData: StageData | null;

  showCO: boolean;
  onShowCOToggle: (show: boolean) => void;
  showNO2: boolean;
  onShowNO2Toggle: (show: boolean) => void;
  showAAI: boolean;
  onShowAAIToggle: (show: boolean) => void;
};

export default function Sidebar({
  onApply,
  onReset,
  districts,
  selectedDistrict,
  onDistrictChange,
  showCurrentStage,
  onCurrentStageToggle,
  showArchive,
  onArchiveToggle,
  selectedArchiveDate,
  onArchiveDateChange,
  stageData,
  showCO,
  onShowCOToggle,
  showNO2,
  onShowNO2Toggle,
  showAAI,
  onShowAAIToggle,
}: Props) {
  const today = dayjs();
  const defaultStart = '2024-09-02';
  const defaultEnd = '2024-11-28';

  const [startDate, setStartDate] = useState<string>(defaultStart);
  const [endDate, setEndDate] = useState<string>(defaultEnd);

  const last24h = {
    start: today.subtract(1, 'day').format('YYYY-MM-DD'),
    end: today.format('YYYY-MM-DD'),
  };

  const last7d = {
    start: today.subtract(7, 'day').format('YYYY-MM-DD'),
    end: today.format('YYYY-MM-DD'),
  };

  // Format date for display (YYYYMMDD -> YYYY-MM-DD)
  const formatDate = (dateStr: string) => {
    if (dateStr.length === 8) {
      return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`;
    }
    return dateStr;
  };

  // Get years in descending order
  const years = stageData ? Object.keys(stageData.years).sort().reverse() : [];

  return (
    <div className="bg-gray-100 p-6 w-80 h-full shadow-md overflow-y-auto">
      <h2 className="text-xl font-bold mb-6">Filters & Controls ⚙️</h2>

      {/* Region (fixed for now) */}
      <div className="mb-6">
        <p className="font-medium text-gray-700 mb-2">Select Region:</p>
        <label className="flex items-center gap-2">
          <input type="radio" checked readOnly />
          Pakistani Punjab
        </label>
      </div>

      {/* District filter */}
      <div className="mb-6">
        <p className="font-medium text-gray-700 mb-2">District</p>
        <select
          className="w-full rounded-md p-2 border border-gray-300"
          value={selectedDistrict}
          onChange={(e) => onDistrictChange(e.target.value)}
        >
          <option value="">All Punjab</option>
          {districts.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <p className="mt-1 text-xs text-gray-500">
          Choosing a district will zoom the map to its boundary.
        </p>
      </div>

      {/* Date Range Picker */}
      <div className="mb-6">
        <p className="font-medium text-gray-700 mb-2">Date Range (Fire Detected)</p>
        <input
          type="date"
          className="w-full rounded-md p-2 border border-gray-300"
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
        />
        <input
          type="date"
          className="w-full rounded-md p-2 border border-gray-300 mt-2"
          value={endDate}
          onChange={(e) => setEndDate(e.target.value)}
        />

        <div className="mt-2 flex gap-2">
          <button
            className="text-sm bg-blue-500 text-white px-2 py-1 rounded"
            onClick={() => {
              setStartDate(last24h.start);
              setEndDate(last24h.end);
            }}
          >
            Last 24h
          </button>
          <button
            className="text-sm bg-blue-500 text-white px-2 py-1 rounded"
            onClick={() => {
              setStartDate(last7d.start);
              setEndDate(last7d.end);
            }}
          >
            Last 7d
          </button>
        </div>

        <div className="mt-4 flex gap-2">
          <button
            className="text-sm bg-green-600 text-white px-3 py-1 rounded"
            onClick={() => onApply(startDate, endDate)}
          >
            Apply
          </button>
          <button
            className="text-sm bg-gray-400 text-white px-3 py-1 rounded"
            onClick={() => {
              setStartDate(defaultStart);
              setEndDate(defaultEnd);
              onReset();
            }}
          >
            Reset
          </button>
        </div>
      </div>

      {/* Layer Controls */}
      <div className="mb-6">
        <p className="font-medium text-gray-700 mb-3">Layer Controls 🗺️</p>
        
        {/* Rice Crop Layer */}
        <label className="flex items-center gap-2 mb-3">
          <input type="checkbox" defaultChecked disabled />
          <span className="text-sm">Rice Crop Area (Pakistan Only)</span>
        </label>

        {/* Current Stage Toggle */}
        <div className="mb-3">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={showCurrentStage}
              onChange={(e) => onCurrentStageToggle(e.target.checked)}
            />
            <span className="text-sm font-medium">Show Current Stage (Pakistan Only)</span>
          </label>
          {showCurrentStage && stageData?.latest && (
            <p className="text-xs text-gray-600 mt-1 ml-6">
              Latest: {formatDate(stageData.latest)}
            </p>
          )}
        </div>

        {/* Archive Toggle */}
        <div className="mb-3">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={showArchive}
              onChange={(e) => onArchiveToggle(e.target.checked)}
            />
            <span className="text-sm font-medium">Show Archive (Pakistan Only)</span>
          </label>
        </div>


        {/* --- NEW HEATMAP TOGGLES --- */}
        <div className="mt-4 pt-4 border-t border-gray-300">
          <p className="text-sm font-medium mb-2">Atmospheric Layers (7-Day Avg)</p>
          <label className="flex items-center gap-2 mb-2">
            <input
              type="checkbox"
              checked={showCO}
              onChange={(e) => onShowCOToggle(e.target.checked)}
            />
            <span className="text-sm">Show CO (Carbon Monoxide)</span>
          </label>
          <label className="flex items-center gap-2 mb-2">
            <input
              type="checkbox"
              checked={showNO2}
              onChange={(e) => onShowNO2Toggle(e.target.checked)}
            />
            <span className="text-sm">Show NO2 (Nitrogen Dioxide)</span>
          </label>
          <label className="flex items-center gap-2 mb-2">
            <input
              type="checkbox"
              checked={showAAI}
              onChange={(e) => onShowAAIToggle(e.target.checked)}
            />
            <span className="text-sm">Show AAI (Aerosol Index)</span>
          </label>
        </div>
        {/* --- END NEW TOGGLES --- */}

        {/* Archive Date Sliders */}
        {showArchive && stageData && (
          <div className="ml-4 mt-3 space-y-3">
            <p className="text-sm font-medium text-gray-600">Select Archive Date:</p>
            
            {years.map((year) => (
              <div key={year} className="bg-white rounded-lg p-3 border">
                <p className="text-sm font-medium mb-2">{year}</p>
                
                {/* Year slider */}
                <div className="space-y-2">
                  <input
                    type="range"
                    min="0"
                    max={stageData.years[year].length - 1}
                    value={stageData.years[year].indexOf(selectedArchiveDate)}
                    onChange={(e) => {
                      const index = parseInt(e.target.value);
                      const selectedDate = stageData.years[year][index];
                      onArchiveDateChange(selectedDate);
                    }}
                    className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                    style={{
                      background: `linear-gradient(to right, #3b82f6 0%, #3b82f6 ${
                        ((stageData.years[year].indexOf(selectedArchiveDate) + 1) / stageData.years[year].length) * 100
                      }%, #e5e7eb ${
                        ((stageData.years[year].indexOf(selectedArchiveDate) + 1) / stageData.years[year].length) * 100
                      }%, #e5e7eb 100%)`
                    }}
                  />
                  
                  {/* Date labels */}
                  <div className="flex justify-between text-xs text-gray-500">
                    <span>{formatDate(stageData.years[year][0])}</span>
                    <span>{formatDate(stageData.years[year][stageData.years[year].length - 1])}</span>
                  </div>
                  
                  {/* Currently selected date */}
                  {stageData.years[year].includes(selectedArchiveDate) && (
                    <div className="text-center">
                      <span className="inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded">
                        Selected: {formatDate(selectedArchiveDate)}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            ))}
            
            {/* Quick date selection */}
            <div className="bg-gray-50 rounded-lg p-3">
              <p className="text-sm font-medium text-gray-600 mb-2">Quick Select:</p>
              <div className="grid grid-cols-2 gap-1">
                {stageData.dates.slice(-8).map((date) => (
                  <button
                    key={date}
                    onClick={() => onArchiveDateChange(date)}
                    className={`text-xs px-2 py-1 rounded transition-colors ${
                      selectedArchiveDate === date
                        ? 'bg-blue-500 text-white'
                        : 'bg-white text-gray-600 hover:bg-gray-100'
                    }`}
                  >
                    {formatDate(date)}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Stage Legend */}
      {(showCurrentStage || showArchive) && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
          <p className="text-sm font-medium text-yellow-800 mb-2">🌾 Rice Growth Stages</p>
          <div className="space-y-1 text-xs text-yellow-700">
            <div>🟢 Early Growth</div>
            <div>🟡 Vegetative</div>
            <div>🟠 Reproductive</div>
            <div>🔴 Maturity</div>
            <div>🟤 Post-Harvest</div>
          </div>
        </div>
      )}
    </div>
  );
}