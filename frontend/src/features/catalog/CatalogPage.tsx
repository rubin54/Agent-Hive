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
    // Ohne das flackert das Raster bei jedem Tastendruck in der Suche auf leer.
    placeholderData: keepPreviousData,
  });

  const sync = useMutation({
    mutationFn: api.sync,
    onSuccess: () => queryClient.invalidateQueries(),
  });

  const patchQuery = (patch: Partial<CatalogQuery>) =>
    // Jede Filteränderung springt zurück auf Seite 1 — sonst zeigt eine engere
    // Auswahl plötzlich eine leere Seite 3.
    setQuery((current) => ({ ...current, ...patch, offset: 0 }));

  const page = models.data;
  const shown = page?.items.length ?? 0;
  const total = page?.total ?? 0;
  const hasMore = page ? page.offset + shown < total : false;

  const headline = useMemo(() => {
    if (!status.data) return null;
    const { model_count, tool_capable_count, vision_capable_count } = status.data;
    return `${model_count} Modelle · ${tool_capable_count} mit Tool-Calling · ${vision_capable_count} mit Bildverständnis`;
  }, [status.data]);

  return (
    <div className="page">
      <header className="topbar">
        <div className="topbar__brand">
          <span className="topbar__mark" aria-hidden="true">
            ⬢
          </span>
          <div>
            <h1>Agent Hive</h1>
            <p className="topbar__sub">{headline ?? "Modellkatalog wird geladen …"}</p>
          </div>
        </div>

        <div className="topbar__meta">
          {status.data && (
            <span className="topbar__snapshot">
              Stand {formatSyncedAt(status.data.synced_at)}
            </span>
          )}
          <button
            type="button"
            className="button"
            onClick={() => sync.mutate()}
            disabled={sync.isPending}
          >
            {sync.isPending ? "Synchronisiere …" : "Katalog aktualisieren"}
          </button>
        </div>
      </header>

      {status.data?.is_fixture && (
        <div className="banner">
          Es läuft der mitgelieferte Katalogstand. Preise und Modellliste können veraltet sein —
          „Katalog aktualisieren" holt den aktuellen Stand von OpenRouter (kein API-Key nötig).
        </div>
      )}

      {sync.isError && (
        <div className="banner banner--error">
          Aktualisierung fehlgeschlagen: {(sync.error as Error).message}
        </div>
      )}

      {status.isError && (
        <div className="banner banner--error">
          Kein Katalog verfügbar: {(status.error as Error).message}
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
              {models.isPending ? "lädt …" : `${total} Treffer`}
              {total > shown && ` — ${shown} angezeigt`}
            </span>
          </div>

          {total === 0 && !models.isPending && (
            <p className="empty">Kein Modell passt auf diese Filter.</p>
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
              Weitere {Math.min(PAGE_SIZE, total - shown)} anzeigen
            </button>
          )}
        </main>

        {selected && <ModelDetail model={selected} onClose={() => setSelected(null)} />}
      </div>
    </div>
  );
}
