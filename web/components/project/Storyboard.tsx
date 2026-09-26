"use client";

import { AlertTriangle, ArrowRight, Clock, Info, ListChecks, Save, Undo2 } from "lucide-react";
import { useState } from "react";
import { api, type Project, type Scene } from "@/lib/api";
import { errorText, roughDuration } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useI18n, type Key } from "@/lib/i18n";
import { ASPECT_CLASS, KIND_META } from "@/lib/meta";
import { Badge, Button, Card, cx, EmptyState, ErrorBox, inputClass, NumberInput, SectionTitle, Skeleton, useToast } from "../ui";
import { useProject } from "./context";

type TextField = "voiceover" | "dialogue" | "headline" | "eyebrow" | "offer" | "prompt";

/** The text fields that matter for a scene: those it has, plus the main one of its kind. */
function fieldsFor(s: Scene): TextField[] {
  const f: TextField[] = [];
  if (s.kind === "shot" || s.prompt) f.push("prompt");
  if (s.dialogue !== null) f.push("dialogue");
  if (s.eyebrow !== null) f.push("eyebrow");
  if (s.headline !== null || s.kind === "title" || s.kind === "endcard") f.push("headline");
  if (s.offer !== null) f.push("offer");
  if (s.voiceover !== null) f.push("voiceover");
  return f;
}

/** Clean a project before PUT: empty optional texts become null, empty caption rows are dropped. */
function cleaned(p: Project): Project {
  return {
    ...p,
    scenes: p.scenes.map((s) => ({
      ...s,
      voiceover: s.voiceover?.trim() ? s.voiceover : null,
      dialogue: s.dialogue?.trim() ? s.dialogue : null,
      headline: s.headline?.trim() ? s.headline : s.kind === "title" || s.kind === "endcard" ? s.headline : null,
      eyebrow: s.eyebrow?.trim() ? s.eyebrow : null,
      offer: s.offer?.trim() ? s.offer : null,
      caption: s.caption.map((c) => c.trim()).filter(Boolean),
    })),
  };
}

function SceneCard({ scene, index, thumb, aspect, onChange }: { scene: Scene; index: number; thumb?: string; aspect: Project["aspect"]; onChange: (s: Scene) => void }) {
  const { t, tx } = useI18n();
  const meta = KIND_META[scene.kind];
  const set = (patch: Partial<Scene>) => onChange({ ...scene, ...patch });
  const vertical = aspect === "9:16" || aspect === "4:5";
  return (
    <Card className="flex flex-col overflow-hidden">
      <div className={cx("flex gap-4 p-4", vertical ? "flex-row" : "flex-col")}>
        <div className={cx("relative shrink-0 overflow-hidden rounded-xl", meta.color, ASPECT_CLASS[aspect], vertical ? "w-28" : "w-full")}>
          {thumb ? (
            // eslint-disable-next-line @next/next/no-img-element -- served by the API through the proxy
            <img src={thumb} alt="" className="size-full object-cover" loading="lazy" />
          ) : (
            <div className="grid size-full place-items-center text-4xl" aria-hidden>
              {meta.emoji}
            </div>
          )}
          <span className="absolute left-2 top-2 grid size-7 place-items-center rounded-full bg-ink/80 text-xs font-bold text-white">{index + 1}</span>
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone="brand">
                <span aria-hidden>{meta.emoji}</span> {tx(`kind.${scene.kind}`, scene.kind)}
              </Badge>
              <span className="font-mono text-xs text-muted">{scene.id}</span>
              {scene.fixes.length > 0 && <Badge tone="amber">{t("fix.count", { n: scene.fixes.length })}</Badge>}
            </div>
            <label className="flex items-center gap-1.5 text-xs text-muted">
              <Clock className="size-3.5" aria-hidden />
              <span className="sr-only">{t("sb.duration")}</span>
              <NumberInput
                value={scene.seconds}
                onChange={(v) => v !== null && set({ seconds: v })}
                step={0.5}
                min={0.5}
                max={30}
                className="!w-20 !px-2 !py-1 text-sm"
                aria-label={`${t("sb.scene", { n: index + 1 })} · ${t("sb.duration")}`}
              />
              s
            </label>
          </div>
        </div>
      </div>
      <div className="flex flex-col gap-3 border-t border-line/70 p-4">
        {fieldsFor(scene).map((f) => (
          <label key={f} className="flex flex-col gap-1">
            <span className="text-xs font-semibold text-muted">{t(`field.${f}` as Key)}</span>
            <textarea
              dir="auto"
              rows={f === "prompt" ? 3 : f === "headline" || f === "eyebrow" || f === "offer" ? 1 : 2}
              value={scene[f] ?? ""}
              onChange={(e) => set({ [f]: e.target.value } as Partial<Scene>)}
              className={cx(inputClass, "resize-y text-sm", f === "headline" && "font-bold")}
            />
            {f === "dialogue" && <span className="text-xs text-amber-700">{t("sb.dialogueNote")}</span>}
          </label>
        ))}
        {(scene.caption.length > 0 || scene.kind === "shot") && (
          <label className="flex flex-col gap-1">
            <span className="text-xs font-semibold text-muted">{t("field.caption")}</span>
            <textarea
              dir="auto"
              rows={Math.max(1, Math.min(4, scene.caption.length))}
              value={scene.caption.join("\n")}
              onChange={(e) => set({ caption: e.target.value.split("\n") })}
              className={cx(inputClass, "resize-y text-sm")}
            />
          </label>
        )}
      </div>
    </Card>
  );
}

function PlanPanel({ onGoRender }: { onGoRender: () => void }) {
  const { t, tx, lang } = useI18n();
  const { id, version } = useProject();
  const plan = useData(`plan:${id}`, () => api.plan(id), version);
  return (
    <Card className="flex flex-col gap-4 p-5">
      <div className="flex items-center gap-2">
        <ListChecks className="size-5 text-brand-600" aria-hidden />
        <h2 className="text-lg font-bold">{t("plan.title")}</h2>
      </div>
      <p className="text-sm text-muted">{t("plan.hint")}</p>
      {plan.error !== undefined && !plan.data && <ErrorBox error={errorText(plan.error, t)} onRetry={plan.reload} />}
      {plan.loading && (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-6" />
          <Skeleton className="h-6" />
        </div>
      )}
      {plan.data && (
        <>
          {plan.data.errors.length > 0 && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-900">
              <p className="mb-1 flex items-center gap-1.5 font-semibold">
                <AlertTriangle className="size-4" aria-hidden /> {t("plan.errors")}
              </p>
              <ul className="list-disc pl-5" dir="auto">
                {plan.data.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          )}
          {plan.data.items.length === 0 ? (
            <p className="text-sm font-medium text-emerald-700">{t("plan.nothing")}</p>
          ) : (
            <ul className="flex flex-col divide-y divide-line/70 text-sm">
              {plan.data.items.map((it) => (
                <li key={it.key} className="flex items-start justify-between gap-3 py-2">
                  <span className="min-w-0">
                    <span className="block font-medium">{tx(`job.stage.${it.stage}`, it.stage)}</span>
                    <span className="block text-xs text-muted" dir="auto">
                      {it.what}
                    </span>
                  </span>
                  <span className="shrink-0 tabular-nums text-muted">{roughDuration(it.seconds, lang)}</span>
                </li>
              ))}
            </ul>
          )}
          {plan.data.warnings.length > 0 && (
            <div className="rounded-xl bg-amber-50 p-3 text-sm text-amber-950">
              <p className="mb-1 flex items-center gap-1.5 font-semibold">
                <Info className="size-4" aria-hidden /> {t("plan.warnings")}
              </p>
              <ul className="list-disc pl-5" dir="auto">
                {plan.data.warnings.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="rounded-xl bg-brand-50 px-3 py-2 text-sm font-semibold text-brand-800">
            {t("plan.total", { t: roughDuration(plan.data.total_seconds, lang) })}
          </p>
          <Button size="lg" onClick={onGoRender} disabled={plan.data.errors.length > 0}>
            {t("render.cta")} <ArrowRight className="size-5" aria-hidden />
          </Button>
        </>
      )}
    </Card>
  );
}

export function Storyboard({ onGoRender }: { onGoRender: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const { id, detail, media, refresh } = useProject();
  const [draft, setDraft] = useState<Project | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const project = draft ?? detail.project;

  const updateScene = (i: number, s: Scene) => {
    const scenes = project.scenes.slice();
    scenes[i] = s;
    setDraft({ ...project, scenes });
    setError(null);
  };

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      await api.saveProject(id, cleaned(draft));
      setDraft(null);
      toast(t("sb.saved"));
      refresh();
    } catch (e) {
      setError(errorText(e, t));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
      <div className="flex min-w-0 flex-col gap-4">
        <SectionTitle title={t("sb.title")} hint={t("sb.hint")} />
        {project.scenes.length === 0 ? (
          <EmptyState emoji="🎞️" title={t("sb.empty")} />
        ) : (
          <ol className={cx("grid gap-4", project.aspect === "9:16" || project.aspect === "4:5" ? "xl:grid-cols-2" : "md:grid-cols-2")}>
            {project.scenes.map((s, i) => (
              <li key={s.id}>
                <SceneCard
                  scene={s}
                  index={i}
                  aspect={project.aspect}
                  thumb={media?.thumbnails[s.id] ?? media?.keyframes[s.id]}
                  onChange={(ns) => updateScene(i, ns)}
                />
              </li>
            ))}
          </ol>
        )}
      </div>
      <aside className="flex flex-col gap-4 lg:sticky lg:top-24 lg:self-start">
        <PlanPanel onGoRender={onGoRender} />
      </aside>

      {draft && (
        <div className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/95 px-4 py-3 shadow-[0_-8px_24px_rgb(30_27_43/0.08)] backdrop-blur">
          <div className="mx-auto flex max-w-7xl flex-col gap-2">
            {error && <ErrorBox error={error} />}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="font-semibold">{t("common.unsaved")}</p>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setDraft(null);
                    setError(null);
                  }}
                  icon={<Undo2 className="size-4" />}
                >
                  {t("common.discard")}
                </Button>
                <Button onClick={save} loading={saving} icon={<Save className="size-4" />}>
                  {t("common.save")}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
