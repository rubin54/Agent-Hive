/** Anzeigeformatierung. Rechnen passiert im Backend in Decimal — hier wird nur dargestellt. */

/**
 * Preis pro Million Token.
 *
 * `null` heißt "unbekannt", nicht "kostenlos" — der Unterschied ist wichtig genug, um im
 * UI sichtbar zu bleiben. OpenRouter liefert für variable Tarife negative Werte, die das
 * Backend bereits zu `null` normalisiert.
 */
export function formatPricePerMTok(value: number | null): string {
  if (value === null) return "unbekannt";
  if (value === 0) return "gratis";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  if (value < 1) return `$${value.toFixed(3)}`;
  return `$${value.toFixed(2)}`;
}

export function formatContext(tokens: number | null): string {
  if (tokens === null) return "—";
  if (tokens >= 1_000_000) {
    const millions = tokens / 1_000_000;
    return `${Number.isInteger(millions) ? millions : millions.toFixed(1)}M`;
  }
  if (tokens >= 1_000) return `${Math.round(tokens / 1_000)}K`;
  return String(tokens);
}

export function formatSyncedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("de-DE", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const ROLE_LABELS: Record<string, string> = {
  scout: "Scout",
  worker: "Worker",
  inspector: "Inspector",
  queen: "Queen",
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}
