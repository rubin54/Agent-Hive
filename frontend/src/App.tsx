import { useState } from "react";

import { CatalogPage } from "./features/catalog/CatalogPage";
import { RunsPage } from "./features/runs/RunsPage";

type View = "catalog" | "runs";

/**
 * Two views, switched by state rather than a router.
 *
 * A router would earn its keep once runs are deep-linkable — which matters from M4, when a
 * sweep produces links worth sharing. Adding it now would be machinery without a user.
 */
export function App() {
  const [view, setView] = useState<View>("catalog");

  return (
    <div className="page">
      <nav className="nav">
        <span className="nav__mark" aria-hidden="true">
          ⬢
        </span>
        <strong className="nav__brand">Agent Hive</strong>
        <button
          type="button"
          className={`nav__tab${view === "catalog" ? " nav__tab--active" : ""}`}
          onClick={() => setView("catalog")}
        >
          Catalog
        </button>
        <button
          type="button"
          className={`nav__tab${view === "runs" ? " nav__tab--active" : ""}`}
          onClick={() => setView("runs")}
        >
          Runs
        </button>
      </nav>

      {view === "catalog" ? <CatalogPage /> : <RunsPage />}
    </div>
  );
}
