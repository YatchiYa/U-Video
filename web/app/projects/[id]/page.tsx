"use client";

import { ArrowLeft, AudioLines, Clapperboard, LayoutGrid, PlayCircle, Settings2, SlidersHorizontal, Wrench } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useHealth } from "@/components/HealthBar";
import { JobPanel } from "@/components/JobPanel";
import { ProjectContext, type ProjectCtx } from "@/components/project/context";
import { FixTab } from "@/components/project/FixTab";
import { RenderTab } from "@/components/project/RenderTab";
import { SettingsTab } from "@/components/project/SettingsTab";
import { Storyboard } from "@/components/project/Storyboard";
import { TimelineTab } from "@/components/project/TimelineTab";
import { VoiceTab } from "@/components/project/VoiceTab";
import { Badge, cx, ErrorBox, Skeleton } from "@/components/ui";
import { api, isRunning, type Job } from "@/lib/api";
import { errorText, languageLabel, timecode } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useI18n, type Key } from "@/lib/i18n";
import { MODE_META } from "@/lib/meta";

const TABS: { id: string; label: Key; icon: typeof LayoutGrid }[] = [
  { id: "storyboard", label: "proj.tab.storyboard", icon: LayoutGrid },
  { id: "render", label: "proj.tab.render", icon: PlayCircle },
  { id: "fix", label: "proj.tab.fix", icon: Wrench },
  { id: "voice", label: "proj.tab.voice", icon: AudioLines },
  { id: "timeline", label: "proj.tab.timeline", icon: SlidersHorizontal },
  { id: "settings", label: "proj.tab.settings", icon: Settings2 },
];

function ProjectPage() {
  const { t, tx, lang } = useI18n();
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(params.id);
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tab = TABS.some((x) => x.id === search.get("tab")) ? search.get("tab")! : "storyboard";
  const health = useHealth();

  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);
  const detail = useData(`project:${id}`, () => api.project(id), version);
  const media = useData(`media:${id}`, () => api.media(id), version);
  const jobs = useData(`jobs:${id}`, () => api.jobs(id, 100), version);

  // progress panels: running jobs of this project (reconnected on arrival) + those started here
  const [tracked, setTracked] = useState<Job[]>([]);
  const [dismissed, setDismissed] = useState<string[]>([]);
  useEffect(() => {
    const running = (jobs.data ?? []).filter(isRunning);
    if (running.length) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- merge jobs found on the server into the panels
      setTracked((tr) => [...tr, ...running.filter((j) => !tr.some((x) => x.id === j.id))]);
    }
  }, [jobs.data]);
  const track = useCallback((job: Job) => {
    setTracked((tr) => (tr.some((x) => x.id === job.id) ? tr : [job, ...tr]));
    setDismissed((d) => d.filter((x) => x !== job.id));
  }, []);

  const ctx = useMemo<ProjectCtx | null>(
    () =>
      detail.data
        ? { id, detail: detail.data, media: media.data ?? null, jobs: jobs.data ?? [], version, refresh, track, workerOk: health ? health.worker : true }
        : null,
    [id, detail.data, media.data, jobs.data, version, refresh, track, health],
  );

  const setTab = (tid: string) => router.replace(`${pathname}?tab=${tid}`, { scroll: false });

  if (detail.error !== undefined && !detail.data) {
    return (
      <div className="flex flex-col gap-4">
        <Link href="/" className="inline-flex items-center gap-1.5 text-sm font-semibold text-muted hover:text-ink">
          <ArrowLeft className="size-4" aria-hidden /> {t("proj.back")}
        </Link>
        <ErrorBox error={errorText(detail.error, t)} onRetry={detail.reload} />
      </div>
    );
  }
  if (!ctx) {
    return (
      <div className="flex flex-col gap-4" role="status">
        <span className="sr-only">{t("common.loading")}</span>
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-12 w-full" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      </div>
    );
  }

  const p = ctx.detail.project;
  const panels = tracked.filter((j) => !dismissed.includes(j.id));
  return (
    <ProjectContext.Provider value={ctx}>
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-3">
          <Link href="/" className="inline-flex w-fit items-center gap-1.5 rounded-lg text-sm font-semibold text-muted hover:text-ink">
            <ArrowLeft className="size-4" aria-hidden /> {t("proj.back")}
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <span className={cx("grid size-12 place-items-center rounded-2xl bg-gradient-to-br text-2xl", MODE_META[p.mode].gradient)} aria-hidden>
              {MODE_META[p.mode].emoji}
            </span>
            <div className="min-w-0">
              <h1 className="truncate text-2xl font-extrabold tracking-tight sm:text-3xl" dir="auto">
                {p.title}
              </h1>
              <div className="mt-1 flex flex-wrap gap-1.5">
                <Badge className={MODE_META[p.mode].tone}>{tx(`mode.${p.mode}`, p.mode)}</Badge>
                <Badge>{p.aspect}</Badge>
                <Badge>{tx(`quality.${p.quality}`, p.quality)}</Badge>
                <Badge>{languageLabel(p.language, lang)}</Badge>
                <Badge>{t("home.scenes", { n: p.scenes.length })}</Badge>
                {ctx.detail.status.total ? <Badge tone="brand">{timecode(ctx.detail.status.total)}</Badge> : null}
              </div>
            </div>
          </div>
        </div>

        {panels.length > 0 && (
          <section aria-label={t("proj.working")} className="flex flex-col gap-3">
            {panels.map((j) => (
              <JobPanel
                key={j.id}
                jobId={j.id}
                initial={j}
                expectation={j.kind === "mix" ? t("mix.hint") : undefined}
                onFinish={() => refresh()}
                onDismiss={() => setDismissed((d) => [...d, j.id])}
              />
            ))}
          </section>
        )}

        <div role="tablist" aria-label={p.title} className="-mx-4 flex gap-1 overflow-x-auto border-b border-line px-4 sm:mx-0 sm:px-0">
          {TABS.map((x) => {
            const Icon = x.icon;
            const active = tab === x.id;
            return (
              <button
                key={x.id}
                role="tab"
                id={`tab-${x.id}`}
                aria-selected={active}
                aria-controls={`panel-${x.id}`}
                onClick={() => setTab(x.id)}
                className={cx(
                  "-mb-px inline-flex shrink-0 items-center gap-2 border-b-[3px] px-3.5 py-3 text-sm font-semibold transition-colors",
                  active ? "border-brand-600 text-brand-700" : "border-transparent text-muted hover:text-ink",
                )}
              >
                <Icon className="size-4" aria-hidden />
                {t(x.label)}
              </button>
            );
          })}
        </div>

        <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
          {tab === "storyboard" && <Storyboard onGoRender={() => setTab("render")} />}
          {tab === "render" && <RenderTab />}
          {tab === "fix" && <FixTab />}
          {tab === "voice" && <VoiceTab />}
          {tab === "timeline" && <TimelineTab />}
          {tab === "settings" && <SettingsTab />}
        </div>
      </div>
    </ProjectContext.Provider>
  );
}

export default function Page() {
  return (
    <Suspense
      fallback={
        <div className="flex flex-col gap-4">
          <Clapperboard className="size-8 animate-pulse text-brand-300" aria-hidden />
        </div>
      }
    >
      <ProjectPage />
    </Suspense>
  );
}
