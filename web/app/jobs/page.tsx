"use client";

import { ArrowRight, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { JobPanel, statusTone } from "@/components/JobPanel";
import { Badge, Button, Card, EmptyState, ErrorBox, SectionTitle, Skeleton } from "@/components/ui";
import { api, isRunning } from "@/lib/api";
import { clock, dateTime, errorText } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useI18n, type Key } from "@/lib/i18n";

export default function JobsPage() {
  const { t, tx, lang } = useI18n();
  const [v, setV] = useState(0);
  const jobs = useData("jobs", () => api.jobs(undefined, 100), v);
  const [follow, setFollow] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now() / 1000);

  // refresh the list every 5 s while something is running
  const anyRunning = (jobs.data ?? []).some(isRunning);
  useEffect(() => {
    if (!anyRunning) return;
    const id = setInterval(() => {
      setV((x) => x + 1);
      setNow(Date.now() / 1000);
    }, 5000);
    return () => clearInterval(id);
  }, [anyRunning]);

  const list = jobs.data ?? [];
  return (
    <div className="flex flex-col gap-6">
      <SectionTitle
        title={t("jobs.title")}
        hint={t("jobs.subtitle")}
        right={
          <Button variant="secondary" size="sm" onClick={() => setV((x) => x + 1)} icon={<RefreshCw className="size-4" />}>
            {t("common.refresh")}
          </Button>
        }
      />
      {follow && <JobPanel key={follow} jobId={follow} onDismiss={() => setFollow(null)} onFinish={() => setV((x) => x + 1)} />}
      {jobs.error !== undefined && !jobs.data && <ErrorBox error={errorText(jobs.error, t)} onRetry={jobs.reload} />}
      {jobs.loading && <Skeleton className="h-64" />}
      {jobs.data && list.length === 0 && <EmptyState emoji="🗂️" title={t("jobs.empty")} />}
      {list.length > 0 && (
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line text-xs uppercase tracking-wide text-muted">
                <th className="px-4 py-3 font-semibold">{t("jobs.what")}</th>
                <th className="px-4 py-3 font-semibold">{t("jobs.project")}</th>
                <th className="px-4 py-3 font-semibold">{t("jobs.status")}</th>
                <th className="px-4 py-3 font-semibold">{t("jobs.when")}</th>
                <th className="px-4 py-3 font-semibold">{t("jobs.duration")}</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-line/70">
              {list.map((j) => {
                const end = j.finished ?? Math.max(now, j.started ?? now);
                return (
                  <tr key={j.id} className="align-top hover:bg-canvas/60">
                    <td className="px-4 py-3">
                      <span className="font-semibold">{tx(`job.kind.${j.kind}`, j.kind)}</span>
                      {j.kind === "export" && typeof j.params.format === "string" && <span className="text-muted"> · {j.params.format}</span>}
                      {j.status === "failed" && j.error && (
                        <p className="mt-1 line-clamp-2 max-w-md text-xs text-red-700" dir="auto">
                          {j.error}
                        </p>
                      )}
                      {isRunning(j) && j.stage && <p className="mt-0.5 text-xs text-muted">{tx(`job.stage.${j.stage}`, j.stage)}</p>}
                    </td>
                    <td className="px-4 py-3">
                      {j.project ? (
                        <Link href={`/projects/${encodeURIComponent(j.project)}`} className="font-medium text-brand-700 hover:underline" dir="auto">
                          {j.project}
                        </Link>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={statusTone(j.status)}>{t(`job.status.${j.status}` as Key)}</Badge>
                    </td>
                    <td className="px-4 py-3 tabular-nums text-muted">{dateTime(j.created, lang)}</td>
                    <td className="px-4 py-3 tabular-nums text-muted">{j.started ? clock(end - j.started) : "—"}</td>
                    <td className="px-4 py-3 text-right">
                      <Button variant="ghost" size="sm" onClick={() => setFollow(j.id)}>
                        {t("jobs.follow")} <ArrowRight className="size-3.5" aria-hidden />
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
