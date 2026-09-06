import { Suspense } from "react";
import WatchlistView from "@/components/WatchlistView";
import Loading from "../loading";

export const metadata = {
  title: "Watchlist · Louichamp Screener",
  description: "Wochen-Watchlist: Markt, Sektoren und Kandidaten nach Priorität.",
};

// Die Watchlist wird montags erzeugt und liegt fertig in der Datenbank; diese
// Seite reicht sie nur durch. Client-Komponente wegen der Wochen-Auswahl.
export default function WatchlistPage() {
  return (
    <Suspense fallback={<Loading />}>
      <WatchlistView />
    </Suspense>
  );
}
