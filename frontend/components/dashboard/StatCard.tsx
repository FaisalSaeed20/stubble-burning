import type { ComponentType, SVGProps } from 'react';

type Trend = { pct: number; label: string } | null;

export default function StatCard({
  icon: Icon,
  iconBgClassName,
  label,
  sublabel,
  value,
  trend,
  isPlaceholder = false,
  placeholderNote,
}: {
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  iconBgClassName: string;
  label: string;
  sublabel?: string;
  value: string;
  trend?: Trend;
  isPlaceholder?: boolean;
  placeholderNote?: string;
}) {
  const trendIsBad = trend != null && trend.pct > 0;
  const trendIsGood = trend != null && trend.pct < 0;

  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-100">
      <div className="flex items-start justify-between">
        <span className="text-sm text-gray-500">{label}</span>
        <span className={`flex h-10 w-10 items-center justify-center rounded-full ${iconBgClassName}`}>
          <Icon className="h-5 w-5" />
        </span>
      </div>

      {isPlaceholder ? (
        <>
          <div className="mt-2 text-3xl font-bold italic text-gray-300">{value}</div>
          <span className="mt-2 inline-block rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
            Not yet available
          </span>
          {placeholderNote && <p className="mt-1 text-xs text-gray-400">{placeholderNote}</p>}
        </>
      ) : (
        <>
          <div className="mt-2 text-3xl font-bold text-gray-900">{value}</div>
          {sublabel && <p className="mt-1 text-sm text-gray-400">{sublabel}</p>}
          {trend && (
            <span
              className={`mt-2 inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                trendIsBad
                  ? 'bg-red-50 text-red-700'
                  : trendIsGood
                  ? 'bg-green-50 text-green-700'
                  : 'bg-gray-100 text-gray-500'
              }`}
            >
              {trendIsBad ? '▲' : trendIsGood ? '▼' : '–'} {Math.abs(trend.pct)}% {trend.label}
            </span>
          )}
        </>
      )}
    </div>
  );
}
