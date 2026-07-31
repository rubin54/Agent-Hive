import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../api/client";
import type { RunSummary, StartRunRequest } from "../../api/types";
import { formatSyncedAt } from "../../lib/format";
import { RunDetail } from "./RunDetail";

export function RunsPage() {
  const [openRun, setOpenRun] = useState<string | null>(null);

  if (openRun) return <RunDetail runId={openRun} onBack={() => setOpenRun(null)} />;
  return <RunList onOpen={setOpenRun} />;
}

function RunList({ onOpen }: { onOpen: (runId: string) => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<StartRunRequest>({
    model_id: "",
    provider: "mock",
    template_name: "",
  });

  const templates = useQuery({ queryKey: ["templates"], queryFn: api.templates });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: api.runs,
    // A plain interval, not the function form: the latter is not re-evaluated after the
    // first response arrives, so a list opened before a run finishes would never update.
    // Refreshing a short list every few seconds costs nothing.
    refetchInterval: 3000,
    // Interval refetching is paused for hidden documents by default. A run keeps going in
    // the background, so a user returning to the tab would otherwise find a frozen list.
    refetchIntervalInBackground: true,
  });

  const start = useMutation({
    mutationFn: (body: StartRunRequest) =>
      api.startRun({
        ...body,
        template_name: body.template_name || undefined,
        goal: body.template_name ? undefined : body.goal,
      }),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      onOpen(run.run_id);
    },
  });

  const usingTemplate = Boolean(form.template_name);

  return (
    <div className="runs">
      <section className="starter">
        <h2>Start a run</h2>
        <div className="starter__row">
          <label className="starter__field">
            <span className="filters__label">Provider</span>
            <select
              className="input"
              value={form.provider}
              onChange={(e) =>
                setForm({ ...form, provider: e.target.value as StartRunRequest["provider"] })
              }
            >
              <option value="mock">mock (recorded, no key)</option>
              <option value="openrouter">openrouter</option>
            </select>
          </label>

          <label className="starter__field">
            <span className="filters__label">Template</span>
            <select
              className="input"
              value={form.template_name ?? ""}
              onChange={(e) => setForm({ ...form, template_name: e.target.value })}
            >
              <option value="">— free-form goal —</option>
              {(templates.data ?? [])
                .filter((t) => !t.error)
                .map((t) => (
                  <option key={t.name} value={t.name}>
                    {t.ref} ({t.checks.length} checks)
                  </option>
                ))}
            </select>
          </label>

          <label className="starter__field starter__field--wide">
            <span className="filters__label">Model</span>
            <input
              className="input"
              placeholder={form.provider === "mock" ? "optional for mock" : "e.g. anthropic/claude-haiku-4.5"}
              value={form.model_id}
              onChange={(e) => setForm({ ...form, model_id: e.target.value })}
            />
          </label>
        </div>

        {!usingTemplate && (
          <label className="starter__field starter__field--wide">
            <span className="filters__label">Goal</span>
            <input
              className="input"
              placeholder="Build a small counter page"
              value={form.goal ?? ""}
              onChange={(e) => setForm({ ...form, goal: e.target.value })}
            />
          </label>
        )}

        {form.provider === "openrouter" && (
          <label className="starter__field starter__field--wide">
            <span className="filters__label">OpenRouter key</span>
            <input
              className="input"
              type="password"
              placeholder="sk-or-…"
              value={form.api_key ?? ""}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })}
            />
            <p className="filters__hint">
              Passed straight through to OpenRouter and never stored — neither in the journal
              nor on disk.
            </p>
          </label>
        )}

        <button
          type="button"
          className="button"
          disabled={start.isPending}
          onClick={() => start.mutate(form)}
        >
          {start.isPending ? "Starting …" : "Start run"}
        </button>

        {start.isError && (
          <div className="banner banner--error">{(start.error as Error).message}</div>
        )}
      </section>

      <section className="run__section">
        <h3>Runs</h3>
        {runs.isPending && <p className="empty">Loading …</p>}
        {runs.data?.length === 0 && <p className="empty">No runs yet.</p>}

        <ul className="runlist">
          {(runs.data ?? []).map((run) => (
            <RunRow key={run.run_id} run={run} onOpen={onOpen} />
          ))}
        </ul>
      </section>
    </div>
  );
}

function RunRow({ run, onOpen }: { run: RunSummary; onOpen: (id: string) => void }) {
  const verdict =
    run.checks_passed === null ? null : run.checks_passed ? "checks passed" : "checks failed";

  return (
    <li>
      <button type="button" className="runrow" onClick={() => onOpen(run.run_id)}>
        <span className={`pill pill--${run.status}`}>{run.live ? "live" : run.status}</span>
        <span className="runrow__model">{run.model_id}</span>
        <span className="runrow__template">{run.template_ref ?? "free-form"}</span>
        <span className="runrow__num">{run.iterations} it</span>
        <span className="runrow__num">{run.total_tokens.toLocaleString("en-GB")} tok</span>
        <span className="runrow__num">
          {run.pricing_known ? `$${Number(run.cost_usd).toFixed(4)}` : "—"}
        </span>
        {verdict && (
          <span className={run.checks_passed ? "runrow__ok" : "runrow__fail"}>{verdict}</span>
        )}
        <span className="runrow__time">{formatSyncedAt(run.started_at)}</span>
      </button>
    </li>
  );
}
