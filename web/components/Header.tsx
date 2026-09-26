"use client";

import { Activity, Clapperboard, Plus } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, isRunning } from "@/lib/api";
import { useI18n, type Lang } from "@/lib/i18n";
import { cx } from "./ui";

function useRunningCount() {
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    const load = () =>
      api.jobs(undefined, 50).then(
        (js) => alive && setN(js.filter(isRunning).length),
        () => undefined,
      );
    load();
    const id = setInterval(load, 8000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);
  return n;
}

export function LangSwitch() {
  const { lang, setLang, t } = useI18n();
  const opts: { id: Lang; label: string }[] = [
    { id: "fr", label: "FR" },
    { id: "en", label: "EN" },
  ];
  return (
    <div role="radiogroup" aria-label={t("lang.label")} className="flex rounded-xl border border-line bg-surface p-0.5">
      {opts.map((o) => (
        <button
          key={o.id}
          role="radio"
          aria-checked={lang === o.id}
          onClick={() => setLang(o.id)}
          className={cx(
            "h-8 rounded-lg px-2.5 text-xs font-bold transition-colors",
            lang === o.id ? "bg-brand-600 text-white" : "text-muted hover:text-ink",
          )}
          lang={o.id}
          title={o.id === "fr" ? "Français" : "English"}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Header() {
  const { t } = useI18n();
  const path = usePathname();
  const running = useRunningCount();
  const link = (href: string, label: string, active: boolean) => (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cx(
        "rounded-xl px-3 py-2 text-sm font-semibold transition-colors",
        active ? "bg-brand-50 text-brand-700" : "text-ink/70 hover:bg-ink/5 hover:text-ink",
      )}
    >
      {label}
    </Link>
  );
  return (
    <header className="sticky top-0 z-30 border-b border-line/80 bg-canvas/85 backdrop-blur">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:rounded-lg focus:bg-surface focus:px-3 focus:py-2">
        {t("skip")}
      </a>
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4 sm:px-6">
        <Link href="/" className="mr-2 flex items-center gap-2.5" aria-label={t("app.name")}>
          <span className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-coral-500 text-white shadow-sm">
            <Clapperboard className="size-5" aria-hidden />
          </span>
          <span className="hidden leading-tight sm:block">
            <span className="block text-[15px] font-extrabold tracking-tight">{t("app.name")}</span>
            <span className="block text-[11px] text-muted">{t("app.tagline")}</span>
          </span>
        </Link>
        <nav className="flex items-center gap-1" aria-label="Main">
          {link("/", t("nav.projects"), path === "/" || path.startsWith("/projects"))}
          <Link
            href="/jobs"
            aria-current={path === "/jobs" ? "page" : undefined}
            className={cx(
              "inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-semibold transition-colors",
              path === "/jobs" ? "bg-brand-50 text-brand-700" : "text-ink/70 hover:bg-ink/5 hover:text-ink",
            )}
          >
            <Activity className="size-4" aria-hidden />
            <span className="hidden sm:inline">{t("nav.jobs")}</span>
            {running > 0 && (
              <span className="rounded-full bg-brand-600 px-1.5 text-[11px] font-bold text-white" title={t("nav.running", { n: running })}>
                {running}
              </span>
            )}
          </Link>
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <LangSwitch />
          {path !== "/create" && (
            <Link
              href="/create"
              className="hidden h-10 items-center gap-2 rounded-xl bg-brand-600 px-4 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 md:inline-flex"
            >
              <Plus className="size-4" aria-hidden />
              {t("nav.create")}
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
