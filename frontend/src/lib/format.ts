/** Display formatting. Arithmetic happens in the backend in Decimal — this only renders. */

/**
 * Price per million tokens.
 *
 * `null` means "unknown", not "free" — the difference matters enough to stay visible in the
 * UI. OpenRouter returns negative values for variable rates, which the backend already
 * normalises to `null`.
 */
export function formatPricePerMTok(value: number | null): string {
  if (value === null) return "unknown";
  if (value === 0) return "free";
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
  return date.toLocaleString("en-GB", {
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
