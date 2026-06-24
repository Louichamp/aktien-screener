import { Suspense } from "react";
import AssetView from "@/components/AssetView";

// Eine einzige statische Detailseite; das Instrument kommt aus ?t=TICKER und wird
// im Client geladen (skaliert auf jede Universumsgröße ohne Build-Aufwand).
export default function AssetPage() {
  return (
    <Suspense fallback={<div className="text-sm text-muted">Lade …</div>}>
      <AssetView />
    </Suspense>
  );
}
