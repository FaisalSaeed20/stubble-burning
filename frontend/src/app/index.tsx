// index.tsx
'use client';

import dynamic from 'next/dynamic';

const MapView = dynamic(() => import('../../components/MapView'), {
  ssr: false,
});

export default function Home() {
  return (
    <main className="h-screen w-full">
      <MapView />
    </main>
  );
}
