import type { CatalogPage, CatalogQuery, CatalogStatus, ProviderFacet } from "./types";

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

export const api = {
  status: () => request<CatalogStatus>("/catalog/status"),
  providers: () => request<ProviderFacet[]>("/catalog/providers"),
  models: (query: CatalogQuery) => request<CatalogPage>(`/catalog/models${toSearchParams(query)}`),
  sync: () => request<{ snapshot_id: string; model_count: number }>("/catalog/sync", {
    method: "POST",
  }),
};
