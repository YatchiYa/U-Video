"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, TERMINAL, type Job, type JobEvent } from "./api";

/**
 * Load data for a key (null = don't load). Keeps showing the previous data while re-fetching,
 * so edits never flash a skeleton; `reload()` or a new `version` re-fetches after a mutation.
 */
export function useData<T>(key: string | null, fetcher: () => Promise<T>, version = 0) {
  const [state, setState] = useState<{ key: string | null; data?: T; error?: unknown }>({ key: null });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (key === null) return;
    let alive = true;
    fetcher().then(
      (data) => alive && setState({ key, data }),
      (error) => alive && setState((s) => ({ key, data: s.key === key ? s.data : undefined, error })),
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the key identifies the request
  }, [key, tick, version]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  const setData = useCallback((data: T) => setState({ key, data }), [key]);
  const fresh = state.key === key;
  return {
    data: fresh ? state.data : undefined,
    error: fresh ? state.error : undefined,
    loading: key !== null && (!fresh || (state.data === undefined && state.error === undefined)),
    reload,
    setData,
  };
}

const EVENT_NAMES = ["queued", "started", "progress", "log", "done", "failed", "cancelled"];

/**
 * Follow a job live with Server-Sent Events (GET /api/jobs/{id}/events); if the stream breaks,
 * fall back to polling GET /api/jobs/{id}. Reconnecting later replays the whole log.
 */
export function useJob<R = unknown>(jobId: string | null, initial?: Job<R> | null) {
  const [job, setJob] = useState<Job<R> | null>(initial ?? null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [live, setLive] = useState(true);
  const initialStatus = initial?.status;

  useEffect(() => {
    if (!jobId) return;
    let closed = false;
    let es: EventSource | null = null;
    let poll: ReturnType<typeof setInterval> | null = null;
    let status: string = initialStatus ?? "queued";

    const refresh = () =>
      api.job<R>(jobId).then(
        (j) => {
          if (closed) return;
          status = j.status;
          setJob(j);
          if (TERMINAL.includes(j.status) && poll) {
            clearInterval(poll);
            poll = null;
          }
        },
        () => undefined,
      );

    refresh();
    try {
      es = new EventSource(api.jobEventsUrl(jobId));
      for (const name of EVENT_NAMES) {
        es.addEventListener(name, (msg) => {
          let ev: JobEvent;
          try {
            ev = JSON.parse((msg as MessageEvent).data);
          } catch {
            return;
          }
          setEvents((prev) => [...prev, ev]);
          if (ev.event === "progress" || ev.event === "started") status = "running";
          setJob((j) => {
            if (!j) return j;
            if (ev.event === "progress") return { ...j, status: "running", stage: ev.stage ?? j.stage, message: ev.message ?? j.message };
            if (ev.event === "started") return { ...j, status: "running", started: ev.t };
            return j;
          });
        });
      }
      es.addEventListener("end", (msg) => {
        try {
          setJob(JSON.parse((msg as MessageEvent).data));
        } catch {
          refresh();
        }
        es?.close();
      });
      es.onerror = () => {
        es?.close();
        if (closed) return;
        setLive(false);
        if (!poll) poll = setInterval(refresh, 3000);
        refresh();
      };
    } catch {
      poll = setInterval(refresh, 3000); // no EventSource: polling only
    }
    // queue position only comes from GET: refresh it now and then while queued
    const slow = setInterval(() => {
      if (status === "queued") refresh();
    }, 5000);

    return () => {
      closed = true;
      es?.close();
      if (poll) clearInterval(poll);
      clearInterval(slow);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only the job id matters
  }, [jobId]);

  return { job, events, live };
}

/** Seconds since `from` (epoch seconds), ticking every second while `running`. */
export function useElapsed(from: number | null | undefined, to: number | null | undefined, running: boolean) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, [running]);
  if (!from) return 0;
  return Math.max(0, (to ?? now) - from);
}

/** Calls `fn` once when `value` becomes true (e.g. a job finished). */
export function useOnce(value: boolean, fn: () => void) {
  const done = useRef(false);
  const cb = useRef(fn);
  useEffect(() => {
    cb.current = fn;
  });
  useEffect(() => {
    if (value && !done.current) {
      done.current = true;
      cb.current();
    }
  }, [value]);
}
