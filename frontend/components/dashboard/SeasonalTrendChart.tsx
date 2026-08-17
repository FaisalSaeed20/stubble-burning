import './chartSetup';
import { Line } from 'react-chartjs-2';
import type { TrendPoint } from './types';

export default function SeasonalTrendChart({
  data,
  title = '90-Day Seasonal Fire Trend',
}: {
  data: TrendPoint[];
  title?: string;
}) {
  const chartData = {
    labels: data.map((row) => row.date),
    datasets: [
      {
        data: data.map((row) => row.count),
        borderColor: '#dc2626',
        backgroundColor: '#dc262620',
        borderWidth: 2,
        pointRadius: 0,
        fill: true,
        tension: 0.3,
      },
    ],
  };

  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-gray-100">
      <h3 className="mb-3 text-sm font-semibold text-gray-700">{title}</h3>
      <div className="h-[180px]">
        <Line
          data={chartData}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { ticks: { maxTicksLimit: 8, autoSkip: true } },
              y: { ticks: { precision: 0 } },
            },
          }}
        />
      </div>
    </div>
  );
}
