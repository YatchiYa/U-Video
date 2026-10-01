"use client";

import { CheckCircle2, Download, FileImage, FileVideo, Film, RotateCw, ShieldCheck, Sparkles, TriangleAlert, XCircle } from "lucide-react";
import { useRef, useState } from "react";
import { api, isRunning, mainVideo, type ExportFormat, type Job, type QaReport, type RenderResult } from "@/lib/api";
import { errorText, fileSize, roughDuration, timecode } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useI18n, type Key } from "@/lib/i18n";
import { Button, Card, cx, EmptyState, Notice, SectionTitle, useToast } from "../ui";
import { useProject } from "./context";
import { VideoPlayer } from "./VideoPlayer";

const EXPORTS: ExportFormat[] = ["tv", "web", "vertical", "square", "portrait", "cover"];
const exportFile = (f: ExportFormat) => (f === "cover" ? "cover.jpg" : `export_${f}.mp4`);

/** The most recent quality report: from a finished render (result.qa) or a qa job. */
function latestQa(jobs: Job[]): QaReport | null {
  for (const j of jobs) {
    if (j.status !== "done" || !j.result) continue;
    if (j.kind === "render" && (j.result as RenderResult).qa) return (j.result as RenderResult).qa!;
    if (j.kind === "qa") return j.result as QaReport;
  }
  return null;
}

export function QaSummary({ qa }: { qa: QaReport }) {
  const { t, tx } = useI18n();
  const Icon = qa.verdict === "PASS" ? CheckCircle2 : qa.verdict === "WARN" ? TriangleAlert : XCircle;
  const tone = qa.verdict === "PASS" ? "text-emerald-700 bg-emerald-50" : qa.verdict === "WARN" ? "text-amber-800 bg-amber-50" : "text-red-800 bg-red-50";
  return (
    <div className="flex flex-col gap-3">
      <p className={cx("flex items-center gap-2 rounded-xl px-3 py-2 font-bold", tone)}>
        <Icon className="size-5" aria-hidden /> {t(`qa.${qa.verdict}` as Key)}
      </p>
      {qa.issues.length > 0 && (
        <ul className="flex flex-col gap-2 text-sm">
          {qa.issues.map((i, k) => (
            <li key={k} className="flex items-start gap-2">
              <span className={cx("mt-1.5 size-2 shrink-0 rounded-full", i.level === "fail" ? "bg-red-500" : "bg-amber-500")} aria-hidden />
              <span>
                <span className="font-semibold">{tx(`qa.check.${i.check}`, i.check)}</span>
                <span className="block text-xs text-muted" dir="auto">
                  {i.detail}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function RenderTab() {
  const { t, tx, lang } = useI18n();
  const toast = useToast();
  const { id, detail, media, jobs, version, track, workerOk } = useProject();
  const plan = useData(`plan:${id}`, () => api.plan(id), version);
  const player = useRef<HTMLVideoElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [target, setTarget] = useState<"high" | "tv" | null>(null); // this render only; null = project setting
  const [now, setNow] = useState(0);

  const video = mainVideo(media);
  const renderRunning = jobs.find((j) => (j.kind === "render" || j.kind === "mix") && isRunning(j));
  const qa = latestQa(jobs);
  const outputs = media?.outputs ?? [];

  const start = async (key: string, fn: () => Promise<Job>) => {
    setBusy(key);
    try {
      track(await fn());
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      toast(errorText(e, t), "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
      <div className="flex min-w-0 flex-col gap-6">
        <Card className="flex flex-col items-center gap-4 bg-gradient-to-br from-brand-50 to-coral-50 p-6 text-center sm:p-8">
          <Button
            size="xl"
            onClick={() => start("render", () => api.render(id, { deliveries: ["web"], qa: true, quality: target }))}
            loading={busy === "render"}
            disabled={!!renderRunning || !workerOk}
            icon={<Sparkles className="size-6" />}
          >
            {video ? t("render.again") : t("render.cta")}
          </Button>
          <div className="flex flex-wrap justify-center gap-2" role="radiogroup" aria-label={t("render.target")}>
            {([null, "high", "tv"] as const).map((q) => (
              <button
                key={q ?? "project"}
                type="button"
                role="radio"
                aria-checked={target === q}
                onClick={() => setTarget(q)}
                className={cx(
                  "rounded-full border px-3 py-1 text-sm transition",
                  target === q ? "border-brand-500 bg-brand-500 text-white" : "border-ink/15 bg-white/70 text-ink/80 hover:border-brand-300",
                )}
              >
                {t(q === "high" ? "render.targetSocial" : q === "tv" ? "render.targetTv" : "render.targetProject")}
              </button>
            ))}
          </div>
          {plan.data && <p className="text-sm text-muted">{t("render.hint", { t: roughDuration(plan.data.total_seconds, lang) })}</p>}
          <p className="max-w-xl text-sm text-ink/70">{t("job.renderExpect")}</p>
          {!workerOk && <Notice tone="amber">{t("health.workerDown")}</Notice>}
        </Card>

        <section>
          <SectionTitle title={t("render.player")} />
          {video ? (
            <VideoPlayer ref={player} src={video} aspect={detail.project.aspect} onTime={(x) => setNow(Math.round(x * 10) / 10)} />
          ) : (
            <EmptyState emoji="🍿" title={t("render.none")} />
          )}
        </section>

        {video && (
          <section>
            <SectionTitle title={t("render.exports")} hint={t("render.exports.hint")} />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {EXPORTS.map((f) => {
                const file = outputs.find((o) => o.name === exportFile(f));
                const running = jobs.some((j) => j.kind === "export" && isRunning(j) && (j.params as { format?: string }).format === f);
                return (
                  <Card key={f} className="flex flex-col gap-3 p-4">
                    <div className="flex items-center gap-2 font-semibold">
                      {f === "cover" ? <FileImage className="size-5 text-brand-600" aria-hidden /> : <FileVideo className="size-5 text-brand-600" aria-hidden />}
                      {t(`export.${f}` as Key)}
                    </div>
                    <div className="mt-auto flex flex-wrap gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        loading={busy === f || running}
                        onClick={() =>
                          start(f, () => api.exportVideo(id, f, f === "cover" ? now : 0))
                        }
                        icon={<RotateCw className="size-3.5" />}
                      >
                        {f === "cover" ? `${t("render.make")} · ${timecode(now)}` : file ? t("render.remake") : t("render.make")}
                      </Button>
                      {file && (
                        <a
                          href={file.url}
                          download={file.name}
                          className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-emerald-600 px-3 text-sm font-semibold text-white hover:bg-emerald-700"
                        >
                          <Download className="size-3.5" aria-hidden />
                          {t("common.download")}
                        </a>
                      )}
                    </div>
                  </Card>
                );
              })}
            </div>
          </section>
        )}
      </div>

      <aside className="flex flex-col gap-4 lg:sticky lg:top-24 lg:self-start">
        <Card className="flex flex-col gap-3 p-5">
          <h2 className="flex items-center gap-2 text-lg font-bold">
            <Download className="size-5 text-brand-600" aria-hidden /> {t("render.downloads")}
          </h2>
          {outputs.length === 0 ? (
            <p className="text-sm text-muted">{t("render.downloads.empty")}</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {outputs.map((o) => (
                <li key={o.name}>
                  <a href={o.url} download={o.name} className="flex items-center justify-between gap-3 rounded-xl px-3 py-2 text-sm hover:bg-brand-50">
                    <span className="flex min-w-0 items-center gap-2">
                      {o.name.endsWith(".mp4") ? <Film className="size-4 shrink-0 text-brand-600" aria-hidden /> : <FileImage className="size-4 shrink-0 text-brand-600" aria-hidden />}
                      <span className="truncate font-medium">{o.name}</span>
                    </span>
                    <span className="shrink-0 text-xs tabular-nums text-muted">{fileSize(o.size)}</span>
                  </a>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="flex flex-col gap-3 p-5">
          <div className="flex items-center justify-between gap-2">
            <h2 className="flex items-center gap-2 text-lg font-bold">
              <ShieldCheck className="size-5 text-brand-600" aria-hidden /> {t("qa.title")}
            </h2>
            {video && (
              <Button variant="ghost" size="sm" className="whitespace-nowrap" loading={busy === "qa"} onClick={() => start("qa", () => api.qa(id))}>
                {t("qa.run")}
              </Button>
            )}
          </div>
          {qa ? <QaSummary qa={qa} /> : <p className="text-sm text-muted">{t("qa.none")}</p>}
        </Card>
        {renderRunning && (
          <Notice tone="brand">
            {tx(`job.kind.${renderRunning.kind}`)} · {t(`job.status.${renderRunning.status}` as Key)}
          </Notice>
        )}
      </aside>
    </div>
  );
}
