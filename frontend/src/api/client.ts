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
    // FastAPI legt die Ursache nach `detail`; ohne das bekäme der Nutzer nur "500".
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* Antwort war kein JSON — dann bleibt es beim Statustext. */
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

function toSearchParams(query: CatalogQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    // Leere Filter dürfen nicht als "" mitgeschickt werden — das Backend
    // würde sie sonst als gesetzten (leeren) Filter behandeln.
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
