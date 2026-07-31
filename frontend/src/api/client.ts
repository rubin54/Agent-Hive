import type {
  CatalogPage,
  CatalogQuery,
  CatalogStatus,
  EventPage,
  ProviderFacet,
  RunSummary,
  StartRunRequest,
  TemplateSummary,
} from "./types";

const API_BASE = "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    // FastAPI puts the cause in `detail`; without it the user would only see "500".
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* Response was not JSON — fall back to the status text. */
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function toSearchParams(query: CatalogQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    // Empty filters must not be sent as "" — the backend would otherwise treat them as
    // a set (empty) filter.
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

/**
 * WebSocket URL for a run's live stream.
 *
 * `after` resumes where a dropped connection left off, so a reconnect neither replays
 * everything nor skips what was missed.
 */
export function runStreamUrl(runId: string, after: number): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${API_BASE}/runs/${runId}/stream?after=${after}`;
}

export function screenshotUrl(runId: string, name: string): string {
  return `${API_BASE}/runs/${runId}/screenshots/${name}`;
}

export const api = {
  status: () => request<CatalogStatus>("/catalog/status"),
  providers: () => request<ProviderFacet[]>("/catalog/providers"),
  models: (query: CatalogQuery) => request<CatalogPage>(`/catalog/models${toSearchParams(query)}`),
  sync: () =>
    request<{ snapshot_id: string; model_count: number }>("/catalog/sync", { method: "POST" }),

  templates: () => request<TemplateSummary[]>("/templates"),

  runs: () => request<RunSummary[]>("/runs"),
  run: (runId: string) => request<RunSummary>(`/runs/${runId}`),
  runEvents: (runId: string, after = -1) =>
    request<EventPage>(`/runs/${runId}/events?after=${after}`),
  startRun: (body: StartRunRequest) => postJson<RunSummary>("/runs", body),
};
