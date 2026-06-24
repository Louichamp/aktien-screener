// Sofortiges Skeleton während der Server-Refetch (Filter/Sort/Seitenwechsel)
// läuft — die Navigation fühlt sich dadurch verzögerungsfrei an.
export default function Loading() {
  return (
    <div className="space-y-4">
      <div>
        <div className="h-6 w-40 animate-pulse rounded bg-panel2" />
        <div className="mt-2 h-4 w-80 animate-pulse rounded bg-panel2/70" />
      </div>
      <div className="h-24 animate-pulse rounded-lg border border-edge bg-panel/60" />
      <div className="overflow-hidden rounded-lg border border-edge bg-panel">
        <div className="h-9 bg-panel2/60" />
        {Array.from({ length: 12 }).map((_, i) => (
          <div key={i} className="flex items-center gap-4 border-b border-edge/40 px-3 py-2.5">
            <div className="h-4 w-40 animate-pulse rounded bg-panel2/70" />
            <div className="ml-auto h-4 w-16 animate-pulse rounded bg-panel2/70" />
            <div className="h-6 w-10 animate-pulse rounded bg-panel2/70" />
            <div className="h-6 w-10 animate-pulse rounded bg-panel2/70" />
            <div className="h-5 w-20 animate-pulse rounded bg-panel2/70" />
          </div>
        ))}
      </div>
    </div>
  );
}
