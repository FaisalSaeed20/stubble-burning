import './chartSetup';
import { Bar } from 'react-chartjs-2';
import type { DistrictCount } from './types';

export default function TopDistrictsChart({ data }: { data: DistrictCount[] }) {
  const chartData = {
    labels: data.map((row) => row.district),
    datasets: [
      {
        data: data.map((row) => row.count),
        backgroundColor: '#dc2626',
        borderRadius: 4,
        maxBarThickness: 24,
      },
    ],
  };

  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-gray-100">
      <h3 className="mb-3 text-sm font-semibold text-gray-700">Top 5 High-Risk Districts</h3>
      <div className="h-[180px]">
        <Bar
          data={chartData}
          options={{
            indexAxis: 'y' as const,
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { ticks: { precision: 0 } },
              y: { grid: { display: false } },
            },
          }}
        />
      </div>
    </div>
  );
}
