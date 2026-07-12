import { Suspense } from "react";
import ScreenerApp from "@/components/ScreenerApp";
import Loading from "./loading";

// Die eigentliche Logik lebt im Client (ScreenerApp), der Daten live von der
// FastAPI-Backend holt (NEXT_PUBLIC_API_BASE). useSearchParams braucht eine
// Suspense-Grenze.
export default function DashboardPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ScreenerApp />
    </Suspense>
  );
}
