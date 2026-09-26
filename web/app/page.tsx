"use client";

import { AlertTriangle, Film, Languages, MoreVertical, Plus, RectangleHorizontal, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { HealthBar, useHealth } from "@/components/HealthBar";
import { Badge, Button, cx, EmptyState, ErrorBox, Modal, SkeletonCards, useToast } from "@/components/ui";
import { api, type ProjectSummary } from "@/lib/api";
import { errorText, languageLabel } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { MODE_META } from "@/lib/meta";

function ProjectCard({ p, onTrash }: { p: ProjectSummary; onTrash: (p: ProjectSummary) => void }) {
  const { t, tx, lang } = useI18n();
  const [menu, setMenu] = useState(false);
  const meta = p.mode ? MODE_META[p.mode] : null;
  return (
    <article className="group relative flex flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-[var(--shadow-soft)] transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-lift)]">
      <Link href={`/projects/${encodeURIComponent(p.id)}`} className="flex flex-1 flex-col focus-visible:outline-offset-[-3px]">
        <div className={cx("relative aspect-video w-full overflow-hidden bg-gradient-to-br", meta?.gradient ?? "from-ink/10 to-ink/5")}>
          {p.video_url ? (
            <video
              src={`${p.video_url}#t=0.8`}
              muted
              playsInline
              preload="metadata"
              className="size-full bg-black/80 object-contain"
              onMouseEnter={(e) => void e.currentTarget.play().catch(() => undefined)}
              onMouseLeave={(e) => e.currentTarget.pause()}
            />
          ) : (
            <div className="grid size-full place-items-center">
              <span className="text-5xl drop-shadow-sm" aria-hidden>
                {p.error ? "⚠️" : meta?.emoji ?? "🎞️"}
              </span>
            </div>
          )}
          {!p.video_url && !p.error && (
            <span className="absolute bottom-2 left-2 rounded-full bg-surface/90 px-2.5 py-1 text-xs font-medium text-muted">
              {t("home.notRendered")}
            </span>
          )}
        </div>
        <div className="flex flex-1 flex-col gap-2 p-4">
          <h2 className="line-clamp-2 text-base font-bold leading-snug" dir="auto">
            {p.title || p.id}
          </h2>
          {p.error ? (
            <p className="flex items-start gap-1.5 text-sm text-red-700">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span className="line-clamp-3">{t("home.broken")}: <span dir="auto">{p.error}</span></span>
            </p>
          ) : (
            <div className="mt-auto flex flex-wrap items-center gap-1.5">
              {p.mode && <Badge className={meta?.tone}>{tx(`mode.${p.mode}`, p.mode)}</Badge>}
              {p.aspect && (
                <Badge>
                  <RectangleHorizontal className="size-3" aria-hidden />
                  {p.aspect}
                </Badge>
              )}
              {p.language && (
                <Badge>
                  <Languages className="size-3" aria-hidden />
                  {languageLabel(p.language, lang)}
                </Badge>
              )}
              {typeof p.scenes === "number" && <Badge>{t("home.scenes", { n: p.scenes })}</Badge>}
            </div>
          )}
        </div>
      </Link>
      <div className="absolute right-2 top-2">
        <button
          aria-label={t("home.trash")}
          aria-haspopup="menu"
          aria-expanded={menu}
          onClick={() => setMenu((m) => !m)}
          className="rounded-lg bg-surface/90 p-1.5 text-muted opacity-0 shadow-sm transition group-hover:opacity-100 focus-visible:opacity-100 aria-expanded:opacity-100"
        >
          <MoreVertical className="size-4" />
        </button>
        {menu && (
          <div role="menu" className="absolute right-0 mt-1 w-48 rounded-xl border border-line bg-surface p-1 shadow-[var(--shadow-lift)]">
            <button
              role="menuitem"
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-red-700 hover:bg-red-50"
              onClick={() => {
                setMenu(false);
                onTrash(p);
              }}
            >
              <Trash2 className="size-4" aria-hidden />
              {t("home.trash")}
            </button>
          </div>
        )}
      </div>
    </article>
  );
}

export default function Home() {
  const { t } = useI18n();
  const toast = useToast();
  const health = useHealth();
  const projects = useData("projects", api.projects);
  const [trash, setTrash] = useState<ProjectSummary | null>(null);
  const [busy, setBusy] = useState(false);

  const doTrash = async () => {
    if (!trash) return;
    setBusy(true);
    try {
      await api.deleteProject(trash.id);
      toast(t("home.trashed"));
      setTrash(null);
    } catch (e) {
      toast(errorText(e, t), "error");
    } finally {
      setBusy(false);
      projects.reload();
    }
  };

  const list = projects.data ?? [];
  return (
    <div className="flex flex-col gap-8">
      <section className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-brand-600 via-brand-500 to-coral-500 p-6 text-white shadow-[var(--shadow-lift)] sm:p-10">
        <div className="relative z-10 max-w-2xl">
          <h1 className="text-3xl font-extrabold tracking-tight sm:text-4xl">{t("home.title")}</h1>
          <p className="mt-2 text-base text-white/85 sm:text-lg">{t("home.subtitle")}</p>
          <Link
            href="/create"
            className="mt-6 inline-flex h-14 items-center gap-3 rounded-2xl bg-white px-7 text-lg font-bold text-brand-700 shadow-lg shadow-brand-900/20 transition hover:scale-[1.02] hover:bg-brand-50"
          >
            <Plus className="size-6" aria-hidden />
            {t("nav.create")}
          </Link>
        </div>
        <Film className="absolute -bottom-8 -right-6 size-56 rotate-12 text-white/10" aria-hidden />
      </section>

      <HealthBar health={health} />

      {projects.error !== undefined && !projects.data ? (
        <ErrorBox error={errorText(projects.error, t)} onRetry={projects.reload} />
      ) : projects.loading ? (
        <SkeletonCards n={6} className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3" />
      ) : list.length === 0 ? (
        <EmptyState
          emoji="🎬"
          title={t("home.emptyTitle")}
          text={t("home.emptyText")}
          action={
            <Link href="/create" className="inline-flex h-12 items-center gap-2 rounded-xl bg-brand-600 px-6 font-semibold text-white hover:bg-brand-700">
              <Plus className="size-5" aria-hidden />
              {t("nav.create")}
            </Link>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {list.map((p) => (
            <ProjectCard key={p.id} p={p} onTrash={setTrash} />
          ))}
        </div>
      )}

      <Modal open={!!trash} onClose={() => setTrash(null)} title={t("home.trash")}>
        <p className="text-ink/80" dir="auto">
          {t("home.trashConfirm", { title: trash?.title || trash?.id || "" })}
        </p>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setTrash(null)}>
            {t("common.cancel")}
          </Button>
          <Button variant="danger" loading={busy} onClick={doTrash} icon={<Trash2 className="size-4" />}>
            {t("home.trash")}
          </Button>
        </div>
      </Modal>
    </div>
  );
}
