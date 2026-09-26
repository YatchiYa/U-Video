"use client";

import { Code2, Cpu, KeyRound } from "lucide-react";
import { api } from "@/lib/api";
import { errorText } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useI18n, type Key } from "@/lib/i18n";
import { Badge, Card, ErrorBox, SectionTitle, Skeleton } from "../ui";
import { useProject } from "./context";

export function SettingsTab() {
  const { t, tx } = useI18n();
  const { id, detail, version } = useProject();
  const prov = useData(`providers:${id}`, () => api.projectProviders(id), version);
  const p = detail.project;

  const sourceLabel = (s: string) => tx(`set.source.${s}`, s);

  return (
    <div className="flex flex-col gap-6">
      <SectionTitle title={t("set.title")} />
      <Card className="p-5">
        <h2 className="flex items-center gap-2 text-lg font-bold">
          <Cpu className="size-5 text-brand-600" aria-hidden /> {t("set.providers")}
        </h2>
        <p className="mt-1 max-w-3xl text-sm text-muted">{t("set.providers.hint")}</p>
        {prov.error !== undefined && !prov.data && <ErrorBox className="mt-4" error={errorText(prov.error, t)} onRetry={prov.reload} />}
        {prov.loading && <Skeleton className="mt-4 h-40" />}
        {prov.data && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-line text-xs uppercase tracking-wide text-muted">
                  <th className="py-2 pr-4 font-semibold">{t("set.col.kind")}</th>
                  <th className="py-2 pr-4 font-semibold">{t("set.col.provider")}</th>
                  <th className="py-2 pr-4 font-semibold">{t("set.col.model")}</th>
                  <th className="py-2 pr-4 font-semibold">{t("set.col.source")}</th>
                  <th className="py-2 font-semibold">{t("set.col.keys")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/70">
                {prov.data.map((r) => {
                  const keys = Object.entries(r.keys);
                  const missing = keys.filter(([, ok]) => !ok).map(([k]) => k);
                  const local = r.provider === "local" || r.provider === "auto" || ["qwen", "chatterbox", "habibi"].includes(r.provider);
                  return (
                    <tr key={r.kind}>
                      <td className="py-3 pr-4 font-semibold">{t(`cap.${r.kind}` as Key)}</td>
                      <td className="py-3 pr-4">
                        {local ? (
                          <Badge tone="green">
                            {t("set.local")}
                            {r.provider !== "local" ? ` · ${tx(`engine.${r.provider}`, r.provider)}` : ""}
                          </Badge>
                        ) : (
                          <Badge tone="blue">{r.provider}</Badge>
                        )}
                      </td>
                      <td className="py-3 pr-4 font-mono text-xs">{r.model ?? <span className="font-sans text-muted">{t("set.defaultModel")}</span>}</td>
                      <td className="py-3 pr-4 text-muted">{sourceLabel(r.source)}</td>
                      <td className="py-3">
                        {keys.length === 0 ? (
                          <span className="text-muted">{t("set.keys.none")}</span>
                        ) : missing.length === 0 ? (
                          <Badge tone="green">
                            <KeyRound className="size-3" aria-hidden /> {t("set.keys.ok")}
                          </Badge>
                        ) : (
                          <Badge tone="red">{t("set.keys.missing", { keys: missing.join(", ") })}</Badge>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card className="p-5">
        <details>
          <summary className="flex cursor-pointer list-none items-center gap-2 text-lg font-bold">
            <Code2 className="size-5 text-brand-600" aria-hidden /> {t("set.raw")}
          </summary>
          <p className="mt-1 text-sm text-muted">{t("set.raw.hint")}</p>
          <pre className="mt-4 max-h-[60vh] overflow-auto rounded-xl bg-ink p-4 font-mono text-xs leading-relaxed text-emerald-100" dir="ltr">
            {JSON.stringify(p, null, 2)}
          </pre>
        </details>
      </Card>
    </div>
  );
}
