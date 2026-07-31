import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, screenshotUrl } from "../../api/client";
import type { RunSummary } from "../../api/types";
import { formatSyncedAt } from "../../lib/format";
import { EventStream } from "./EventStream";
import { useRunStream } from "./useRunStream";

interface Props {
  runId: string;
  onBack: () => void;
}

const CONNECTION_LABEL: Record<string, string> = {
  loading: "loading",
  live: "live",
  closed: "finished",
  error: "stream unavailable",
};

export function RunDetail({ runId, onBack }: Props) {
  const [autoScroll, setAutoScroll] = useState(true);

  // An explicit flag rather than deriving the interval from the query's own data: the
  // function form of refetchInterval is not re-evaluated once the first response arrives,
  // so the polling would never start. Settle when the run reaches a terminal state.
  const [settled, setSettled] = useState(false);

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId),
    // The summary is polled; the events come over the socket. Polling both would double the
    // traffic for no gain.
    refetchInterval: settled ? false : 1500,
    // Without this the poll stops whenever the tab is hidden, and a run watched in a
    // background tab would appear frozen until the user comes back.
    refetchIntervalInBackground: true,
  });

  const isLive = run.data?.live ?? false;
  const { events, connection } = useRunStream(runId, isLive);

  useEffect(() => {
    if (run.data && !run.data.live && run.data.status !== "running") setSettled(true);
  }, [run.data]);

  // The checks run after the last event, so the closing frame is the earliest moment the
  // final summary exists. Fetching right then avoids showing a stale result for a tick.
  useEffect(() => {
    if (connection === "closed") void run.refetch();
  }, [connection]); // eslint-disable-line react-hooks/exhaustive-deps

  if (run.isPending) return <p className="empty">Loading run …</p>;
  if (run.isError || !run.data) {
    return <p className="empty">Run not found: {(run.error as Error)?.message}</p>;
  }

  const data: RunSummary = run.data;
  const cost = Number(data.cost_usd);

  return (
    <div className="run">
      <header className="run__head">
        <button type="button" className="button button--ghost" onClick={onBack}>
          ← All runs
        </button>
        <span className={`pill pill--${data.status}`}>{data.status}</span>
        {data.live && <span className="pill pill--live">{CONNECTION_LABEL[connection]}</span>}
      </header>

      <h2 className="run__title">{data.model_id}</h2>
      <p className="run__goal">{data.goal}</p>

      <dl className="run__stats">
        <div>
          <dt>Template</dt>
          <dd>{data.template_ref ?? "—"}</dd>
        </div>
        <div>
          <dt>Iterations</dt>
          <dd>{data.iterations}</dd>
        </div>
        <div>
          <dt>Tokens</dt>
          <dd>{data.total_tokens.toLocaleString("en-GB")}</dd>
        </div>
        <div>
          <dt>Cost</dt>
          <dd title={data.pricing_known ? undefined : "no catalog prices for this model"}>
            {data.pricing_known ? `$${cost.toFixed(5)}` : "unknown"}
          </dd>
        </div>
        <div>
          <dt>Started</dt>
          <dd>{formatSyncedAt(data.started_at)}</dd>
        </div>
        <div>
          <dt>Provider</dt>
          <dd>{data.provider}</dd>
        </div>
      </dl>

      {data.stop_reason && (
        <p className="run__stop">
          <strong>{data.stop_reason}</strong> — {data.detail}
        </p>
      )}

      {data.check_summary.length > 0 && (
        <section className="run__section">
          <h3>Checks {data.checks_passed ? "passed" : "failed"}</h3>
          <ul className="checkrows">
            {data.check_summary.map((check) => (
              <li key={check.name} className={check.passed ? "checkrow checkrow--ok" : "checkrow checkrow--fail"}>
                <span className="checkrow__name">{check.name}</span>
                <span className="checkrow__time">{check.duration_seconds.toFixed(1)}s</span>
                {!check.passed && <pre className="checkrow__detail">{check.detail.slice(0, 800)}</pre>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {data.screenshots.length > 0 && (
        <section className="run__section">
          <h3>Screenshots</h3>
          <div className="shots">
            {data.screenshots.map((name) => (
              <a
                key={name}
                href={screenshotUrl(runId, name)}
                target="_blank"
                rel="noreferrer"
                className="shots__item"
              >
                <img src={screenshotUrl(runId, name)} alt={name} loading="lazy" />
                <span>{name}</span>
              </a>
            ))}
          </div>
        </section>
      )}

      <section className="run__section">
        <div className="run__stream-head">
          <h3>Event stream ({events.length})</h3>
          <label className="check">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
            />
            follow
          </label>
        </div>
        <EventStream events={events} autoScroll={autoScroll} />
      </section>

      {data.workspace && (
        <section className="run__section">
          <h3>Workspace</h3>
          <pre className="workspace">{data.workspace}</pre>
        </section>
      )}
    </div>
  );
}
