import type { CatalogQuery, ProviderFacet, Role, SortKey } from "../../api/types";
import { roleLabel } from "../../lib/format";

interface Props {
  query: CatalogQuery;
  providers: ProviderFacet[];
  onChange: (patch: Partial<CatalogQuery>) => void;
  onReset: () => void;
}

const ROLES: Role[] = ["scout", "worker", "inspector", "queen"];

const ROLE_HINTS: Record<Role, string> = {
  scout: "Exploration — needs no tools, plans in text",
  worker: "Elaboration — needs tool calling",
  inspector: "Verification — needs image understanding",
  queen: "Synthesis — needs tool calling",
};

const SORTS: { value: SortKey; label: string }[] = [
  { value: "name", label: "Name" },
  { value: "price_asc", label: "Price ascending" },
  { value: "price_desc", label: "Price descending" },
  { value: "context_desc", label: "Context descending" },
  { value: "newest", label: "Newest first" },
];

export function Filters({ query, providers, onChange, onReset }: Props) {
  return (
    <aside className="filters">
      <div className="filters__group">
        <label className="filters__label" htmlFor="search">
          Search
        </label>
        <input
          id="search"
          type="search"
          className="input"
          placeholder="Name, id or description"
          value={query.search ?? ""}
          onChange={(e) => onChange({ search: e.target.value || undefined })}
        />
      </div>

      <div className="filters__group">
        <span className="filters__label">Role in the swarm</span>
        <div className="chips">
          {ROLES.map((role) => (
            <button
              key={role}
              type="button"
              title={ROLE_HINTS[role]}
              className={`chip${query.role === role ? " chip--active" : ""}`}
              onClick={() => onChange({ role: query.role === role ? undefined : role })}
            >
              {roleLabel(role)}
            </button>
          ))}
        </div>
      </div>

      <div className="filters__group">
        <span className="filters__label">Capabilities</span>
        <label className="check">
          <input
            type="checkbox"
            checked={query.supports_tools === true}
            onChange={(e) => onChange({ supports_tools: e.target.checked || undefined })}
          />
          Tool calling
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={query.supports_vision === true}
            onChange={(e) => onChange({ supports_vision: e.target.checked || undefined })}
          />
          Image understanding
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={query.free_only === true}
            onChange={(e) => onChange({ free_only: e.target.checked || undefined })}
          />
          Free only
        </label>
      </div>

      <div className="filters__group">
        <label className="filters__label" htmlFor="maxprice">
          Blended price at most <span className="filters__unit">$/MTok</span>
        </label>
        <input
          id="maxprice"
          type="number"
          className="input"
          min={0}
          step={0.25}
          placeholder="no limit"
          value={query.max_blended_usd_per_mtok ?? ""}
          onChange={(e) =>
            onChange({
              max_blended_usd_per_mtok: e.target.value ? Number(e.target.value) : undefined,
            })
          }
        />
        <p className="filters__hint">
          Blended price = 3:1 weighting of input and output. Models without a known price drop
          out of this filter.
        </p>
      </div>

      <div className="filters__group">
        <label className="filters__label" htmlFor="mincontext">
          Context at least
        </label>
        <select
          id="mincontext"
          className="input"
          value={query.min_context_length ?? ""}
          onChange={(e) =>
            onChange({ min_context_length: e.target.value ? Number(e.target.value) : undefined })
          }
        >
          <option value="">any</option>
          <option value={32_000}>32K</option>
          <option value={128_000}>128K</option>
          <option value={256_000}>256K</option>
          <option value={1_000_000}>1M</option>
        </select>
      </div>

      <div className="filters__group">
        <label className="filters__label" htmlFor="provider">
          Provider
        </label>
        <select
          id="provider"
          className="input"
          value={query.provider ?? ""}
          onChange={(e) => onChange({ provider: e.target.value || undefined })}
        >
          <option value="">all</option>
          {providers.map((facet) => (
            <option key={facet.provider} value={facet.provider}>
              {facet.provider} ({facet.count})
            </option>
          ))}
        </select>
      </div>

      <div className="filters__group">
        <label className="filters__label" htmlFor="sort">
          Sorting
        </label>
        <select
          id="sort"
          className="input"
          value={query.sort ?? "name"}
          onChange={(e) => onChange({ sort: e.target.value as SortKey })}
        >
          {SORTS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <button type="button" className="button button--ghost" onClick={onReset}>
        Reset filters
      </button>
    </aside>
  );
}
