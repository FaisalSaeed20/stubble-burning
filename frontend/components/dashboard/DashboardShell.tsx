'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';
import TopNav from './TopNav';
import ProvincialSummary from './ProvincialSummary';
import DistrictAnalytics from './DistrictAnalytics';
import IncidentExplorer from './IncidentExplorer';
import type { TabKey } from './types';

const MapView = dynamic(() => import('../MapView'), { ssr: false });

export default function DashboardShell() {
  const [activeTab, setActiveTab] = useState<TabKey>('summary');

  return (
    <div className="flex h-screen w-full flex-col">
      <TopNav activeTab={activeTab} onTabChange={setActiveTab} />
      <div className="min-h-0 flex-1 overflow-auto">
        {activeTab === 'summary' && <ProvincialSummary />}
        {activeTab === 'district' && <DistrictAnalytics />}
        {activeTab === 'incident' && <IncidentExplorer />}
        {activeTab === 'map' && <MapView />}
      </div>
    </div>
  );
}
