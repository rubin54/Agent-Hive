/**
 * Hand-maintained mirror of the API types for M0.
 *
 * From M3 these types are generated from FastAPI's OpenAPI schema via `make types`
 * (`openapi-typescript`) and this file becomes a pure re-export. Pydantic stays the single
 * schema source — nothing is invented here that the backend does not serve.
 */

export type Role = "scout" | "worker" | "inspector" | "queen";

export type SortKey = "name" | "price_asc" | "price_desc" | "context_desc" | "newest";

export interface ModelSummary {
  id: string;
  name: string;
  provider: string;
  description: string | null;
  created: number | null;
  context_length: number | null;
  max_completion_tokens: number | null;
  prompt_usd_per_mtok: number | null;
  completion_usd_per_mtok: number | null;
  blended_usd_per_mtok: number | null;
  pricing_known: boolean;
  supports_tools: boolean;
  supports_vision: boolean;
  supports_structured_output: boolean;
  is_free: boolean;
  reasoning_efforts: string[];
  roles: Role[];
  ineligible_reason: string | null;
}

export interface CatalogPage {
  snapshot_id: string;
  synced_at: string;
  total: number;
  offset: number;
  limit: number;
  items: ModelSummary[];
}

export interface CatalogStatus {
  snapshot_id: string;
  synced_at: string;
  source: string;
  model_count: number;
  is_fixture: boolean;
  tool_capable_count: number;
  vision_capable_count: number;
}

export interface ProviderFacet {
  provider: string;
  count: number;
}

export interface CatalogQuery {
  search?: string;
  provider?: string;
  role?: Role;
  supports_tools?: boolean;
  supports_vision?: boolean;
  free_only?: boolean;
  max_blended_usd_per_mtok?: number;
  min_context_length?: number;
  sort?: SortKey;
  offset?: number;
  limit?: number;
}
