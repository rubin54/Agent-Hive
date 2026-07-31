import type { ModelSummary } from "../../api/types";
import { formatContext, formatPricePerMTok, roleLabel } from "../../lib/format";

interface Props {
  model: ModelSummary;
  onClose: () => void;
}

export function ModelDetail({ model, onClose }: Props) {
  return (
    <section className="detail" aria-label={`Details zu ${model.name}`}>
      <header className="detail__head">
        <div>
          <h2>{model.name}</h2>
          <code className="detail__id">{model.id}</code>
        </div>
        <button type="button" className="button button--ghost" onClick={onClose}>
          Schließen
        </button>
      </header>

      {model.description && <p className="detail__description">{model.description}</p>}

      <div className="detail__grid">
        <div>
          <span className="detail__key">Eingabe</span>
          <span className="detail__value">
            {formatPricePerMTok(model.prompt_usd_per_mtok)} / MTok
          </span>
        </div>
        <div>
          <span className="detail__key">Ausgabe</span>
          <span className="detail__value">
            {formatPricePerMTok(model.completion_usd_per_mtok)} / MTok
          </span>
        </div>
        <div>
          <span className="detail__key">Mischpreis (3:1)</span>
          <span className="detail__value">
            {formatPricePerMTok(model.blended_usd_per_mtok)} / MTok
          </span>
        </div>
        <div>
          <span className="detail__key">Kontext</span>
          <span className="detail__value">{formatContext(model.context_length)}</span>
        </div>
        <div>
          <span className="detail__key">Max. Ausgabe</span>
          <span className="detail__value">{formatContext(model.max_completion_tokens)}</span>
        </div>
        <div>
          <span className="detail__key">Strukturierte Ausgabe</span>
          <span className="detail__value">{model.supports_structured_output ? "ja" : "nein"}</span>
        </div>
      </div>

      <div className="detail__section">
        <span className="detail__key">Rollen im Schwarm</span>
        <ul className="tile__roles">
          {model.roles.map((role) => (
            <li key={role} className={`role role--${role}`}>
              {roleLabel(role)}
            </li>
          ))}
        </ul>
        {model.ineligible_reason && <p className="detail__warning">{model.ineligible_reason}</p>}
      </div>

      {model.reasoning_efforts.length > 0 && (
        <div className="detail__section">
          <span className="detail__key">Reasoning-Stufen</span>
          <p className="detail__value">{model.reasoning_efforts.join(", ")}</p>
          <p className="filters__hint">
            Unterschiedliche Denkstufen sind nicht direkt vergleichbar. Der Benchmark fährt
            die Standardstufe und weist sie im Ergebnis aus.
          </p>
        </div>
      )}

      <p className="detail__soon">
        Rollenzuweisung und Sweep-Start folgen in M5 — hier wird das Modell später in eine
        Hive-Komposition gezogen.
      </p>
    </section>
  );
}
