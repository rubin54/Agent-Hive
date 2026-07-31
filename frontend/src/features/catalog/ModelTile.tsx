import type { ModelSummary } from "../../api/types";
import { formatContext, formatPricePerMTok, roleLabel } from "../../lib/format";

interface Props {
  model: ModelSummary;
  selected: boolean;
  onSelect: (model: ModelSummary) => void;
}

export function ModelTile({ model, selected, onSelect }: Props) {
  // Modelle ohne Tool-Calling werden gedämpft dargestellt, aber nicht ausgeblendet:
  // Wer wissen will, warum ein Modell für einen Schwarmlauf ausfällt, soll es sehen.
  const limited = model.ineligible_reason !== null;

  return (
    <button
      type="button"
      className={`tile${selected ? " tile--selected" : ""}${limited ? " tile--limited" : ""}`}
      onClick={() => onSelect(model)}
      aria-pressed={selected}
    >
      <header className="tile__head">
        <span className="tile__provider">{model.provider}</span>
        {model.is_free && <span className="badge badge--free">gratis</span>}
      </header>

      <h3 className="tile__name" title={model.id}>
        {model.name}
      </h3>

      <dl className="tile__stats">
        <div>
          <dt>Ein</dt>
          <dd>{formatPricePerMTok(model.prompt_usd_per_mtok)}</dd>
        </div>
        <div>
          <dt>Aus</dt>
          <dd>{formatPricePerMTok(model.completion_usd_per_mtok)}</dd>
        </div>
        <div>
          <dt>Kontext</dt>
          <dd>{formatContext(model.context_length)}</dd>
        </div>
      </dl>

      <ul className="tile__roles">
        {model.roles.map((role) => (
          <li key={role} className={`role role--${role}`}>
            {roleLabel(role)}
          </li>
        ))}
      </ul>

      {limited && <p className="tile__note">{model.ineligible_reason}</p>}
    </button>
  );
}
