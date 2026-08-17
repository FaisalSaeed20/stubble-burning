export default function ComingSoon({ title }: { title: string }) {
  return (
    <div className="flex h-full w-full items-center justify-center bg-gray-50">
      <div className="text-center">
        <h2 className="text-lg font-semibold text-gray-700">{title}</h2>
        <p className="mt-1 text-sm text-gray-400">Coming soon</p>
      </div>
    </div>
  );
}
