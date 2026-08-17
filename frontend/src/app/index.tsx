// index.tsx
'use client';

import dynamic from 'next/dynamic';

const DashboardShell = dynamic(() => import('../../components/dashboard/DashboardShell'), {
  ssr: false,
});

export default function Home() {
  return (
    <main className="h-screen w-full">
      <DashboardShell />
    </main>
  );
}
