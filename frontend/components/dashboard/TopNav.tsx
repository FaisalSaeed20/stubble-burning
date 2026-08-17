import { FireIcon } from '@heroicons/react/24/solid';
import type { TabKey } from './types';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'summary', label: 'Provincial Summary' },
  { key: 'district', label: 'District Analytics' },
  { key: 'incident', label: 'Incident Explorer' },
  { key: 'map', label: 'Interactive Map' },
];

export default function TopNav({
  activeTab,
  onTabChange,
}: {
  activeTab: TabKey;
  onTabChange: (tab: TabKey) => void;
}) {
  return (
    <header className="flex h-16 w-full flex-shrink-0 items-center justify-between border-b border-gray-200 bg-white px-6">
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-red-100">
          <FireIcon className="h-6 w-6 text-red-600" />
        </span>
        <div>
          <h1 className="text-sm font-bold leading-tight text-gray-900">Punjab Rice Stubble Burning Monitor</h1>
          <p className="text-xs leading-tight text-gray-500">Government of Punjab, Pakistan</p>
        </div>
      </div>

      <nav className="flex gap-1">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => onTabChange(tab.key)}
            className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.key ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </nav>
    </header>
  );
}
