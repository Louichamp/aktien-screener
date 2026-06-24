import { Suspense } from "react";
import ScreenerApp from "@/components/ScreenerApp";
import Loading from "./loading";

// Statische Seite: die eigentliche Logik lebt im Client (ScreenerApp), der die
// exportierten JSON-Daten lädt. useSearchParams braucht eine Suspense-Grenze.
export default function DashboardPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ScreenerApp />
    </Suspense>
  );
}
