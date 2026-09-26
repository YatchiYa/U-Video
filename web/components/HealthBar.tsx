"use client";

import { Cpu, PlugZap, Server, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Health } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cx } from "./ui";

/** GET /api/health every 15 s. `null` = still checking, `false` = API unreachable. */
export function useHealth() {
  const [h, setH] = useState<Health | null | false>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      api.health().then(
        (x) => alive && setH(x),
        () => alive && setH(false),
      );
    load();
    const id = setInterval(load, 15000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);
  return h;
}

function Chip({ ok, icon, children }: { ok: boolean | null; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium",
        ok === null ? "border-line text-muted" : ok ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-300 bg-amber-50 text-amber-900",
      )}
    >
      <span className={cx("size-2 rounded-full", ok === null ? "bg-ink/20" : ok ? "bg-emerald-500" : "bg-amber-500")} aria-hidden />
      {icon}
      {children}
    </span>
  );
}

export function HealthBar({ health }: { health: Health | null | false }) {
  const { t } = useI18n();
  if (health === null) {
    return (
      <div className="flex flex-wrap gap-2" role="status">
        <Chip ok={null} icon={<Server className="size-3.5" aria-hidden />}>
          {t("health.checking")}
        </Chip>
      </div>
    );
  }
  if (health === false) {
    return (
      <div role="alert" className="flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">
        <PlugZap className="mt-0.5 size-5 shrink-0 text-red-600" aria-hidden />
        <p>{t("health.apiDown")}</p>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2" role="status">
        <Chip ok={health.ok && health.store_ok} icon={<Server className="size-3.5" aria-hidden />}>
          {t("health.ready")}
        </Chip>
        {health.worker && (
          <Chip ok icon={<PlugZap className="size-3.5" aria-hidden />}>
            {t("health.worker")}
          </Chip>
        )}
        <Chip ok={!!health.gpu} icon={<Cpu className="size-3.5" aria-hidden />}>
          {health.gpu ? t("health.gpu", { gpu: health.gpu }) : t("health.noGpu")}
        </Chip>
      </div>
      {!health.worker && (
        <div role="alert" className="flex items-start gap-3 rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
          <TriangleAlert className="mt-0.5 size-5 shrink-0 text-amber-600" aria-hidden />
          <p>{t("health.workerDown")}</p>
        </div>
      )}
    </div>
  );
}
