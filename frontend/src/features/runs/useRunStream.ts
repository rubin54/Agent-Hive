import { useCallback, useEffect, useRef, useState } from "react";

import { api, runStreamUrl } from "../../api/client";
import type { RunEvent } from "../../api/types";

type Connection = "loading" | "live" | "closed" | "error";

interface StreamState {
  events: RunEvent[];
  connection: Connection;
}

/**
 * Events of a run: the recorded ones first, then live ones for as long as it is running.
 *
 * The REST backfill comes first on purpose. It makes the view complete even when WebSockets
 * are blocked by a proxy, and it gives the socket a sequence number to resume from.
 *
 * Everything is deduplicated by sequence rather than assumed to arrive exactly once. React's
 * StrictMode runs effects twice in development, and the socket may be (re)opened after the
 * backfill has already delivered part of the range — without dedupe both would double up.
 */
export function useRunStream(runId: string, isLive: boolean): StreamState {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connection, setConnection] = useState<Connection>("loading");

  // Refs rather than state: the socket callbacks need current values without re-subscribing
  // on every single event.
  const seen = useRef<Set<number>>(new Set());
  const lastSequence = useRef(-1);

  const append = useCallback((incoming: RunEvent[]) => {
    const fresh = incoming.filter((event) => !seen.current.has(event.sequence));
    if (!fresh.length) return;
    for (const event of fresh) {
      seen.current.add(event.sequence);
      lastSequence.current = Math.max(lastSequence.current, event.sequence);
    }
    setEvents((current) => [...current, ...fresh].sort((a, b) => a.sequence - b.sequence));
  }, []);

  // Backfill — runs once per run, independent of whether it is still live.
  useEffect(() => {
    let cancelled = false;
    setEvents([]);
    setConnection("loading");
    seen.current = new Set();
    lastSequence.current = -1;

    api
      .runEvents(runId)
      .then((page) => {
        if (cancelled) return;
        append(page.events);
        if (!page.live) setConnection("closed");
      })
      .catch(() => {
        if (!cancelled) setConnection("error");
      });

    return () => {
      cancelled = true;
    };
  }, [runId, append]);

  // Live socket — opened only while the run is in flight. Re-running this effect is
  // harmless because append() drops anything already seen.
  useEffect(() => {
    if (!isLive) return;

    let cancelled = false;
    const socket = new WebSocket(runStreamUrl(runId, lastSequence.current));

    socket.onopen = () => {
      if (!cancelled) setConnection("live");
    };
    socket.onmessage = (message) => {
      if (cancelled) return;
      const parsed = JSON.parse(message.data as string) as RunEvent | { type: string };
      if (parsed.type === "stream_closed") {
        setConnection("closed");
        return;
      }
      append([parsed as RunEvent]);
    };
    socket.onerror = () => {
      if (!cancelled) setConnection("error");
    };
    socket.onclose = () => {
      if (!cancelled) setConnection((state) => (state === "live" ? "closed" : state));
    };

    return () => {
      cancelled = true;
      socket.close();
    };
  }, [runId, isLive, append]);

  return { events, connection };
}
