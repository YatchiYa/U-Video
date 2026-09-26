"use client";

import { Check, Mic, RefreshCw, Upload, Volume2 } from "lucide-react";
import { useRef, useState } from "react";
import { api, DIALECTS, VOICE_ENGINES, type Dialect, type VoiceEngine, type VoiceLine } from "@/lib/api";
import { errorText } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useI18n, type Key } from "@/lib/i18n";
import { Badge, Button, Card, cx, EmptyState, ErrorBox, Field, inputClass, Notice, SectionTitle, Skeleton, useToast } from "../ui";
import { useProject } from "./context";

const CLOUD: VoiceEngine[] = ["elevenlabs", "openai", "gemini"];

/** "Update the sound" call to action (narration + mix only, video untouched). */
export function MixButton({ highlight }: { highlight?: boolean }) {
  const { t } = useI18n();
  const toast = useToast();
  const { id, jobs, track, workerOk } = useProject();
  const [busy, setBusy] = useState(false);
  const running = jobs.some((j) => (j.kind === "mix" || j.kind === "render") && (j.status === "queued" || j.status === "running"));
  return (
    <Card className={cx("flex flex-col items-start gap-3 p-5 transition", highlight && "border-brand-300 bg-brand-50 ring-4 ring-brand-100")}>
      {highlight && <p className="text-sm font-semibold text-brand-800">{t("mix.changed")}</p>}
      <Button
        size="lg"
        loading={busy}
        disabled={running || !workerOk}
        onClick={async () => {
          setBusy(true);
          try {
            track(await api.mix(id));
            window.scrollTo({ top: 0, behavior: "smooth" });
          } catch (e) {
            toast(errorText(e, t), "error");
          } finally {
            setBusy(false);
          }
        }}
        icon={<Volume2 className="size-5" />}
      >
        {t("mix.cta")}
      </Button>
      <p className="text-sm text-muted">{t("mix.hint")}</p>
    </Card>
  );
}

function LineRow({ line, onSaved, onRedo }: { line: VoiceLine; onSaved: () => void; onRedo: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const { id } = useProject();
  const [text, setText] = useState(line.text);
  const [base, setBase] = useState(line.text);
  const [saving, setSaving] = useState(false);
  const [redoing, setRedoing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (line.text !== base) {
    // the server text changed (after a reload): follow it
    setBase(line.text);
    setText(line.text);
  }
  const dirty = text.trim() !== line.text.trim() && text.trim().length > 0;
  const quality = line.quality ?? line.mos;

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.setVoiceText(id, line.id, text.trim());
      toast(t("voice.saved"));
      onSaved();
    } catch (e) {
      setError(errorText(e, t));
    } finally {
      setSaving(false);
    }
  };

  return (
    <tr className="align-top">
      <td className="py-3 pr-3">
        <span className="font-mono text-xs text-muted">{line.id}</span>
      </td>
      <td className="min-w-64 py-3 pr-3">
        <textarea
          dir="auto"
          rows={2}
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-label={`${t("voice.col.text")} · ${line.id}`}
          className={cx(inputClass, "resize-y text-sm")}
        />
        {dirty && (
          <div className="mt-1.5 flex gap-2">
            <Button size="sm" loading={saving} onClick={save} icon={<Check className="size-3.5" />}>
              {t("common.save")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setText(line.text)}>
              {t("common.cancel")}
            </Button>
          </div>
        )}
        {error && <ErrorBox className="mt-2" error={error} />}
      </td>
      <td className="py-3 pr-3 tabular-nums">
        {line.score != null ? (
          <span className={cx("font-semibold", line.score >= 0.95 ? "text-emerald-700" : line.score >= 0.85 ? "text-amber-700" : "text-red-700")}>
            {Math.round(line.score * 100)} %
          </span>
        ) : (
          "—"
        )}
      </td>
      <td className="py-3 pr-3 tabular-nums">{quality != null ? `${quality.toFixed(1)} / 5` : "—"}</td>
      <td className="py-3 pr-3 tabular-nums">{line.seconds != null ? `${line.seconds.toFixed(1)} s` : "—"}</td>
      <td className="max-w-56 py-3 pr-3 text-xs text-muted" dir="auto">
        {line.heard ?? "—"}
      </td>
      <td className="py-3 pr-3">
        {line.stale ? <Badge tone="amber">{t("voice.stale")}</Badge> : line.score != null ? <Badge tone="green">{t("voice.ready")}</Badge> : <Badge>{t("voice.notYet")}</Badge>}
      </td>
      <td className="py-3">
        <Button
          size="sm"
          variant="secondary"
          loading={redoing}
          icon={<RefreshCw className="size-3.5" />}
          onClick={async () => {
            setRedoing(true);
            try {
              await api.redoVoice(id, [line.id]);
              toast(t("voice.newTakeDone"));
              onRedo();
            } catch (e) {
              toast(errorText(e, t), "error");
            } finally {
              setRedoing(false);
            }
          }}
        >
          {t("voice.newTake")}
        </Button>
      </td>
    </tr>
  );
}

function EngineCard({ current, onChanged }: { current: string; onChanged: () => void }) {
  const { t, tx } = useI18n();
  const toast = useToast();
  const { id, detail } = useProject();
  const pv = detail.project.voice;
  const [engine, setEngine] = useState<VoiceEngine>(pv.file ? "auto" : pv.engine);
  const [voiceId, setVoiceId] = useState(pv.voice_id ?? "");
  const [dialect, setDialect] = useState<Dialect | "">(pv.dialect ?? "");
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const arabic = detail.project.language.toLowerCase() === "arabic" || engine === "habibi";

  const apply = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.setVoiceEngine(id, {
        engine,
        voice_id: CLOUD.includes(engine) ? voiceId.trim() || null : null,
        dialect: arabic && dialect ? dialect : null,
      });
      toast(t("common.saved"));
      onChanged();
    } catch (e) {
      setError(errorText(e, t));
    } finally {
      setBusy(false);
    }
  };

  const upload = async (f: File | undefined) => {
    if (!f) return;
    setUploading(true);
    setError(null);
    try {
      await api.voiceFile(id, f);
      toast(t("common.saved"));
      onChanged();
    } catch (e) {
      setError(errorText(e, t));
    } finally {
      setUploading(false);
      if (file.current) file.current.value = "";
    }
  };

  return (
    <Card className="flex flex-col gap-4 p-5">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-bold">
          <Mic className="size-5 text-brand-600" aria-hidden /> {t("voice.engine")}
        </h2>
        <p className="mt-1 text-sm text-muted">{t("voice.engine.hint")}</p>
        <p className="mt-2 text-sm">
          <Badge tone="brand">{t("voice.engine.current", { engine: tx(`engine.${current}`, current) })}</Badge>
        </p>
      </div>
      <Field label={t("voice.engine")} htmlFor="engine">
        <select id="engine" value={engine} onChange={(e) => setEngine(e.target.value as VoiceEngine)} className={inputClass}>
          {VOICE_ENGINES.map((e) => (
            <option key={e} value={e}>
              {tx(`engine.${e}`, e)}
            </option>
          ))}
        </select>
      </Field>
      {CLOUD.includes(engine) && (
        <Field label={t("voice.voiceId")} htmlFor="voiceid" optional>
          <input id="voiceid" value={voiceId} onChange={(e) => setVoiceId(e.target.value)} className={inputClass} />
        </Field>
      )}
      {arabic && (
        <Field label={t("voice.dialect")} htmlFor="dialect" optional>
          <select id="dialect" value={dialect} onChange={(e) => setDialect(e.target.value as Dialect | "")} className={inputClass}>
            <option value="">—</option>
            {DIALECTS.map((d) => (
              <option key={d} value={d}>
                {t(`dialect.${d}` as Key)}
              </option>
            ))}
          </select>
        </Field>
      )}
      <Button variant="secondary" loading={busy} onClick={apply}>
        {t("voice.useEngine")}
      </Button>
      {error && <ErrorBox error={error} />}
      <div className="border-t border-line pt-4">
        <h3 className="font-bold">{t("voice.own")}</h3>
        <p className="mt-1 text-sm text-muted">{t("voice.own.hint")}</p>
        {pv.file && (
          <p className="mt-2 break-all text-sm font-medium text-emerald-700">{t("voice.own.current", { file: pv.file.split("/").pop() ?? pv.file })}</p>
        )}
        <Button className="mt-3" variant="soft" loading={uploading} onClick={() => file.current?.click()} icon={<Upload className="size-4" />}>
          {t("voice.own")}
        </Button>
        <input ref={file} type="file" accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg,.flac" hidden onChange={(e) => upload(e.target.files?.[0])} />
      </div>
    </Card>
  );
}

export function VoiceTab() {
  const { t } = useI18n();
  const { id, detail, version, refresh } = useProject();
  const voice = useData(`voice:${id}`, () => api.voice(id), version);
  const [changed, setChanged] = useState(false);
  const after = () => {
    setChanged(true);
    refresh();
  };
  const stale = voice.data?.lines.some((l) => l.stale) ?? false;

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
      <div className="flex min-w-0 flex-col gap-4">
        <SectionTitle title={t("voice.title")} hint={t("voice.hint")} />
        {!detail.project.voice.enabled && <Notice tone="blue">{t("voice.disabled")}</Notice>}
        {voice.error !== undefined && !voice.data && <ErrorBox error={errorText(voice.error, t)} onRetry={voice.reload} />}
        {voice.loading && <Skeleton className="h-48" />}
        {voice.data &&
          (voice.data.lines.length === 0 ? (
            <EmptyState emoji="🎙️" title={t("voice.empty")} text={t("voice.empty.hint")} />
          ) : (
            <Card className="overflow-x-auto p-4">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-line text-xs uppercase tracking-wide text-muted">
                    <th className="py-2 pr-3 font-semibold">#</th>
                    <th className="py-2 pr-3 font-semibold">{t("voice.col.text")}</th>
                    <th className="py-2 pr-3 font-semibold">{t("voice.col.accuracy")}</th>
                    <th className="py-2 pr-3 font-semibold">{t("voice.col.quality")}</th>
                    <th className="py-2 pr-3 font-semibold">{t("voice.col.length")}</th>
                    <th className="py-2 pr-3 font-semibold">{t("voice.col.heard")}</th>
                    <th className="py-2 pr-3 font-semibold">{t("voice.col.status")}</th>
                    <th className="py-2 font-semibold">
                      <span className="sr-only">{t("voice.newTake")}</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/70">
                  {voice.data.lines.map((l) => (
                    <LineRow key={l.id} line={l} onSaved={after} onRedo={after} />
                  ))}
                </tbody>
              </table>
            </Card>
          ))}
      </div>
      <aside className="flex flex-col gap-4 lg:sticky lg:top-24 lg:self-start">
        <MixButton highlight={changed || stale} />
        {voice.data && <EngineCard key={version} current={voice.data.engine} onChanged={after} />}
      </aside>
    </div>
  );
}
