// Kubische Bézier-Kurvenglättung (Catmull-Rom -> Bézier).
//
// Catmull-Rom legt eine C1-stetige Kurve exakt DURCH alle Stützpunkte; die
// Umrechnung in kubische Béziers ergibt saubere SVG-`C`-Pfade ohne Überschwingen.
// Das ist dasselbe Verfahren wie d3.curveCatmullRom, hier dependency-frei.

export interface Pt {
  x: number;
  y: number;
}

// `tension` 0..1: 1 = klassisches Catmull-Rom (rund), 0 = quasi gerade.
function controlPoints(p0: Pt, p1: Pt, p2: Pt, p3: Pt, tension: number) {
  const t = tension / 6;
  return {
    cp1: { x: p1.x + (p2.x - p0.x) * t, y: p1.y + (p2.y - p0.y) * t },
    cp2: { x: p2.x - (p3.x - p1.x) * t, y: p2.y - (p3.y - p1.y) * t },
  };
}

/** Geglätteter offener Pfad durch alle Punkte: "M … C …". */
export function smoothLinePath(points: Pt[], tension = 1): string {
  const n = points.length;
  if (n === 0) return "";
  if (n === 1) return `M${points[0].x},${points[0].y}`;
  if (n === 2) return `M${points[0].x},${points[0].y} L${points[1].x},${points[1].y}`;

  let d = `M${points[0].x},${points[0].y}`;
  for (let i = 0; i < n - 1; i++) {
    const p0 = points[i - 1] ?? points[i]; // Endpunkte gespiegelt
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] ?? p2;
    const { cp1, cp2 } = controlPoints(p0, p1, p2, p3, tension);
    d += ` C${cp1.x},${cp1.y} ${cp2.x},${cp2.y} ${p2.x},${p2.y}`;
  }
  return d;
}

/**
 * Geschlossener, geglätteter Flächenpfad: obere Grenze vorwärts, untere Grenze
 * rückwärts — für den schattierten Konfidenzkanal. Beide Ränder werden separat
 * geglättet, damit sich die Kanalbreite sauber verengt/weitet.
 */
export function smoothAreaPath(upper: Pt[], lower: Pt[], tension = 1): string {
  if (upper.length === 0 || lower.length === 0) return "";
  const top = smoothLinePath(upper, tension);
  // untere Grenze rückwärts; führendes "M" -> "L", um anzuschließen statt neu zu starten
  const bottom = smoothLinePath([...lower].reverse(), tension).replace(/^M/, "L");
  return `${top} ${bottom} Z`;
}
