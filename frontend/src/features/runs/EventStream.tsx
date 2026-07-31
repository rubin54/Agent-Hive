import { useEffect, useRef } from "react";

import type { RunEvent } from "../../api/types";

interface Props {
  events: RunEvent[];
  autoScroll: boolean;
}

const LABELS: Record<string, string> = {
  run_started: "run started",
  iteration_started: "iteration",
  model_called: "model called",
  model_responded: "model responded",
  tool_called: "tool",
  tool_returned: "result",
  run_finished: "run finished",
};

function asString(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** One line per event — the same data the journal holds, nothing summarised away. */
function describe(event: RunEvent): { text: string; tone: "" | "ok" | "fail" | "muted" } {
  const p = event.payload;
  switch (event.type) {
    case "run_started":
      return { text: `tools: ${asString(p.tools)}`, tone: "muted" };
    case "iteration_started":
      return { text: `#${asString(p.iteration)}`, tone: "muted" };
    case "model_called":
      return { text: `${asString(p.message_count)} messages in context`, tone: "muted" };
    case "model_responded": {
      const usage = (p.usage ?? {}) as Record<string, number>;
      const calls = Array.isArray(p.tool_calls) ? (p.tool_calls as string[]) : [];
      const tokens = `${usage.prompt_tokens ?? 0}→${usage.completion_tokens ?? 0} tokens`;
      const cost = p.cost_usd ? ` · $${Number(p.cost_usd).toFixed(5)}` : "";
      return { text: `${tokens}${cost}${calls.length ? ` · wants ${calls.join(", ")}` : ""}`, tone: "" };
    }
    case "tool_called":
      return { text: `${asString(p.name)}(${asString(p.arguments).slice(0, 160)})`, tone: "" };
    case "tool_returned":
      return {
        text: `${asString(p.name)} → ${asString(p.result).slice(0, 200)}`,
        tone: p.ok === true ? "ok" : "fail",
      };
    case "run_finished":
      return { text: `${asString(p.reason)} — ${asString(p.detail)}`, tone: "" };
    default:
      return { text: asString(p), tone: "muted" };
  }
}

export function EventStream({ events, autoScroll }: Props) {
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll) bottom.current?.scrollIntoView({ block: "end" });
  }, [events.length, autoScroll]);

  if (!events.length) {
    return <p className="empty">No events yet.</p>;
  }

  return (
    <ol className="stream">
      {events.map((event) => {
        const { text, tone } = describe(event);
        return (
          <li key={event.sequence} className={`stream__row stream__row--${event.type}`}>
            <span className="stream__seq">{event.sequence}</span>
            <span className="stream__type">{LABELS[event.type] ?? event.type}</span>
            <span className={`stream__text${tone ? ` stream__text--${tone}` : ""}`}>{text}</span>
          </li>
        );
      })}
      <div ref={bottom} />
    </ol>
  );
}
