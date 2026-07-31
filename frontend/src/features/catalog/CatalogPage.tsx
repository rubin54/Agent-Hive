import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "../../api/client";
import type { CatalogQuery, ModelSummary } from "../../api/types";
import { formatSyncedAt } from "../../lib/format";
import { Filters } from "./Filters";
import { ModelDetail } from "./ModelDetail";
import { ModelTile } from "./ModelTile";

const PAGE_SIZE = 60;
const DEFAULT_QUERY: CatalogQuery = { sort: "name", limit: PAGE_SIZE, offset: 0 };

export function CatalogPage() {
  const [query, setQuery] = useState<CatalogQuery>(DEFAULT_QUERY);
  const [selected, setSelected] = useState<ModelSummary | null>(null);
  const queryClient = useQueryClient();

  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers });
  const models = useQuery({
    queryKey: ["models", query],
    queryFn: () => api.models(query),
    // Without this the grid flashes empty on every keystroke in the search box.
    placeholderData: keepPreviousData,
  });

  const sync = useMutation({
    mutationFn: api.sync,
    onSuccess: () => queryClient.invalidateQueries(),
  });

  const patchQuery = (patch: Partial<CatalogQuery>) =>
    // Any filter change jumps back to page 1 — otherwise a narrower selection would suddenly
    // show an empty page 3.
    setQuery((current) => ({ ...current, ...patch, offset: 0 }));

  const page = models.data;
  const shown = page?.items.length ?? 0;
  const total = page?.total ?? 0;
  const hasMore = page ? page.offset + shown < total : false;

  const headline = useMemo(() => {
    if (!status.data) return null;
    const { model_count, tool_capable_count, vision_capable_count } = status.data;
    return `${model_count} models · ${tool_capable_count} with tool calling · ${vision_capable_count} with image understanding`;
  }, [status.data]);

  return (
    <>
      <header className="topbar">
        <div className="topbar__brand">
          <div>
            <h1>Model catalog</h1>
            <p className="topbar__sub">{headline ?? "Loading model catalog …"}</p>
          </div>
        </div>

        <div className="topbar__meta">
          {status.data && (
            <span className="topbar__snapshot">as of {formatSyncedAt(status.data.synced_at)}</span>
          )}
          <button
            type="button"
            className="button"
            onClick={() => sync.mutate()}
            disabled={sync.isPending}
          >
            {sync.isPending ? "Syncing …" : "Refresh catalog"}
          </button>
        </div>
      </header>

      {status.data?.is_fixture && (
        <div className="banner">
          Running on the bundled catalog state. Prices and the model list may be out of date —
          "Refresh catalog" fetches the current state from OpenRouter (no API key needed).
        </div>
      )}

      {sync.isError && (
        <div className="banner banner--error">
          Refresh failed: {(sync.error as Error).message}
        </div>
      )}

      {status.isError && (
        <div className="banner banner--error">
          No catalog available: {(status.error as Error).message}
        </div>
      )}

      <div className="layout">
        <Filters
          query={query}
          providers={providers.data ?? []}
          onChange={patchQuery}
          onReset={() => setQuery(DEFAULT_QUERY)}
        />

        <main className="results">
          <div className="results__head">
            <span>
              {models.isPending ? "loading …" : `${total} matches`}
              {total > shown && ` — showing ${shown}`}
            </span>
          </div>

          {total === 0 && !models.isPending && (
            <p className="empty">No model matches these filters.</p>
          )}

          <div className="grid">
            {page?.items.map((model) => (
              <ModelTile
                key={model.id}
                model={model}
                selected={selected?.id === model.id}
                onSelect={setSelected}
              />
            ))}
          </div>

          {hasMore && (
            <button
              type="button"
              className="button button--wide"
              onClick={() =>
                setQuery((current) => ({
                  ...current,
                  limit: (current.limit ?? PAGE_SIZE) + PAGE_SIZE,
                }))
              }
            >
              Show {Math.min(PAGE_SIZE, total - shown)} more
            </button>
          )}
        </main>

        {selected && <ModelDetail model={selected} onClose={() => setSelected(null)} />}
      </div>
    </>
  );
}
