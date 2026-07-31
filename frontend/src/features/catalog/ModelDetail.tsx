import type { ModelSummary } from "../../api/types";
import { formatContext, formatPricePerMTok, roleLabel } from "../../lib/format";

interface Props {
  model: ModelSummary;
  onClose: () => void;
}

export function ModelDetail({ model, onClose }: Props) {
  return (
    <section className="detail" aria-label={`Details for ${model.name}`}>
      <header className="detail__head">
        <div>
          <h2>{model.name}</h2>
          <code className="detail__id">{model.id}</code>
        </div>
        <button type="button" className="button button--ghost" onClick={onClose}>
          Close
        </button>
      </header>

      {model.description && <p className="detail__description">{model.description}</p>}

      <div className="detail__grid">
        <div>
          <span className="detail__key">Input</span>
          <span className="detail__value">
            {formatPricePerMTok(model.prompt_usd_per_mtok)} / MTok
          </span>
        </div>
        <div>
          <span className="detail__key">Output</span>
          <span className="detail__value">
            {formatPricePerMTok(model.completion_usd_per_mtok)} / MTok
          </span>
        </div>
        <div>
          <span className="detail__key">Blended (3:1)</span>
          <span className="detail__value">
            {formatPricePerMTok(model.blended_usd_per_mtok)} / MTok
          </span>
        </div>
        <div>
          <span className="detail__key">Context</span>
          <span className="detail__value">{formatContext(model.context_length)}</span>
        </div>
        <div>
          <span className="detail__key">Max output</span>
          <span className="detail__value">{formatContext(model.max_completion_tokens)}</span>
        </div>
        <div>
          <span className="detail__key">Structured output</span>
          <span className="detail__value">{model.supports_structured_output ? "yes" : "no"}</span>
        </div>
      </div>

      <div className="detail__section">
        <span className="detail__key">Roles in the swarm</span>
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
          <span className="detail__key">Reasoning levels</span>
          <p className="detail__value">{model.reasoning_efforts.join(", ")}</p>
          <p className="filters__hint">
            Different reasoning levels are not directly comparable. The benchmark runs the
            model's default and reports it alongside the result.
          </p>
        </div>
      )}

      <p className="detail__soon">
        Role assignment and sweep start arrive in M5 — this is where a model will be dragged
        into a hive composition.
      </p>
    </section>
  );
}
