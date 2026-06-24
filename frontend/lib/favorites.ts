// Lokale Favoriten/Watchlist via localStorage (keine Server-Persistenz nötig).
const KEY = "louichamp_favorites_v1";

export function getFavorites(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

export function saveFavorites(list: string[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(Array.from(new Set(list))));
  } catch {
    /* localStorage nicht verfügbar */
  }
}

export function toggleFavorite(list: string[], ticker: string): string[] {
  const next = list.includes(ticker) ? list.filter((t) => t !== ticker) : [...list, ticker];
  saveFavorites(next);
  return next;
}
