"use client";

import { CheckCircle2, ChevronDown, CircleSlash, Clock, Hourglass, WifiOff, XCircle } from "lucide-react";
import { useState } from "react";
import { api, isRunning, TERMINAL, type Job } from "@/lib/api";
import { clock, errorText } from "@/lib/format";
import { useElapsed, useJob, useOnce } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { Badge, Button, Card, cx, ErrorBox, Spinner } from "./ui";

const RENDER_STAGES = ["frames", "shots", "fixes", "voice", "music", "edit", "qa"];
const MIX_STAGES = ["voice", "music", "edit"];

export function statusTone(s: Job["status"]) {
  return s === "done" ? "green" : s === "failed" ? "red" : s === "cancelled" ? "neutral" : s === "running" ? "brand" : "amber";
}

/**
 * Live progress of one job: stage, message log, elapsed time, Cancel. Survives leaving the page:
 * reopening it replays the whole log from the API.
 */
export function JobPanel<R = unknown>({
  jobId,
  initial,
  onFinish,
  onDismiss,
  expectation,
  className,
}: {
  jobId: string;
  initial?: Job<R> | null;
  onFinish?: (job: Job<R>) => void;
  onDismiss?: () => void;
  expectation?: string;
  className?: string;
}) {
  const { t, tx } = useI18n();
  const { job, events, live } = useJob<R>(jobId, initial);
  const [open, setOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const status = job?.status ?? "queued";
  const running = !TERMINAL.includes(status);
  const elapsed = useElapsed(job?.started ?? job?.created, job?.finished, running);

  useOnce(!!job && !running, () => job && onFinish?.(job));

  const cancel = async () => {
    setCancelling(true);
    setCancelError(null);
    try {
      await api.cancelJob(jobId);
    } catch (e) {
      setCancelError(errorText(e, t));
      setCancelling(false);
    }
  };

  const kind = job?.kind ?? "render";
  const stages = kind === "render" ? RENDER_STAGES : kind === "mix" ? MIX_STAGES : null;
  const stageIdx = stages && job?.stage ? stages.indexOf(job.stage) : -1;
  const logLines = events.filter((e) => e.message && (e.event === "progress" || e.event === "log" || e.event === "failed"));
  const t0 = job?.created ?? 0;

  return (
    <Card className={cx("overflow-hidden", className)} aria-live="polite">
      <div className={cx("h-1.5 w-full", running ? "bg-brand-100" : status === "done" ? "bg-emerald-400" : status === "failed" ? "bg-red-400" : "bg-ink/10")}>
        {running && <div className="job-slide h-full w-1/3 rounded-full bg-brand-500" />}
      </div>
      <div className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <div className="mt-0.5">
              {status === "done" ? (
                <CheckCircle2 className="size-7 text-emerald-600" aria-hidden />
              ) : status === "failed" ? (
                <XCircle className="size-7 text-red-600" aria-hidden />
              ) : status === "cancelled" ? (
                <CircleSlash className="size-7 text-muted" aria-hidden />
              ) : status === "queued" ? (
                <Hourglass className="size-7 text-amber-600" aria-hidden />
              ) : (
                <Spinner className="size-7" />
              )}
            </div>
            <div className="min-w-0">
              <h3 className="text-lg font-bold">{tx(`job.kind.${kind}`, kind)}</h3>
              <p className="text-[15px] text-ink/80">
                {status === "running"
                  ? job?.stage
                    ? tx(`job.stage.${job.stage}`, job.stage)
                    : t("job.starting")
                  : status === "queued"
                    ? t("job.waiting")
                    : status === "done"
                      ? t("job.done")
                      : status === "cancelled"
                        ? t("job.cancelled")
                        : t("job.failed")}
              </p>
              {running && job?.message && job.message !== "starting" && job.message !== "waiting for the worker" && (
                <p className="mt-0.5 truncate text-sm text-muted" dir="auto">
                  {job.message}
                </p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge tone={statusTone(status)}>{t(`job.status.${status}` as never)}</Badge>
            <span className="inline-flex items-center gap-1 text-sm tabular-nums text-muted">
              <Clock className="size-4" aria-hidden />
              {t("job.elapsed", { t: clock(elapsed) })}
            </span>
          </div>
        </div>

        {stages && running && (
          <ol className="mt-4 flex flex-wrap gap-1.5" aria-label={tx(`job.kind.${kind}`, kind)}>
            {stages.map((s, i) => (
              <li
                key={s}
                className={cx(
                  "rounded-full px-2.5 py-1 text-xs font-medium",
                  i < stageIdx ? "bg-emerald-50 text-emerald-700" : i === stageIdx ? "bg-brand-600 text-white" : "bg-ink/5 text-muted",
                )}
                aria-current={i === stageIdx ? "step" : undefined}
              >
                {tx(`job.stage.${s}`, s)}
              </li>
            ))}
          </ol>
        )}

        {status === "queued" && job?.position ? <p className="mt-3 text-sm text-muted">{t("job.position", { n: job.position })}</p> : null}

        {running && (expectation || kind === "render") && (
          <p className="mt-4 rounded-xl bg-brand-50 px-4 py-3 text-sm text-brand-900">
            {expectation ?? t("job.renderExpect")} {t("job.leave")}
          </p>
        )}
        {running && !live && (
          <p className="mt-3 inline-flex items-center gap-1.5 text-xs text-muted">
            <WifiOff className="size-3.5" aria-hidden /> {t("job.lostConnection")}
          </p>
        )}

        {status === "failed" && job?.error && <ErrorBox className="mt-4" error={job.error} />}
        {cancelError && <ErrorBox className="mt-4" error={cancelError} />}

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-sm font-medium text-muted hover:bg-ink/5 hover:text-ink"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            <ChevronDown className={cx("size-4 transition-transform", open && "rotate-180")} aria-hidden />
            {open ? t("job.details.hide") : t("job.details.show")}
          </button>
          <div className="flex gap-2">
            {job && isRunning(job) && (
              <Button variant="danger" size="sm" onClick={cancel} loading={cancelling}>
                {cancelling ? t("job.cancelling") : t("job.cancel")}
              </Button>
            )}
            {!running && onDismiss && (
              <Button variant="ghost" size="sm" onClick={onDismiss}>
                {t("job.dismiss")}
              </Button>
            )}
          </div>
        </div>
        {open && (
          <ol className="mt-3 max-h-64 overflow-auto rounded-xl bg-ink/[0.03] p-3 font-mono text-xs leading-relaxed">
            {logLines.length === 0 && <li className="text-muted">…</li>}
            {logLines.map((e, i) => (
              <li key={i} className="flex gap-3">
                <span className="shrink-0 tabular-nums text-muted">{clock(e.t - t0)}</span>
                {e.stage && <span className="shrink-0 text-brand-700">{e.stage}</span>}
                <span className="whitespace-pre-wrap break-words" dir="auto">
                  {e.message}
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </Card>
  );
}
