"use client";

import { Clapperboard, Info, Sparkles, Undo2, Wand2, Zap } from "lucide-react";
import { useRef, useState } from "react";
import { api, mainVideo, type FixIn, type FixResult } from "@/lib/api";
import { errorText, round, timecode } from "@/lib/format";
import { useI18n, type Key } from "@/lib/i18n";
import { KIND_META } from "@/lib/meta";
import { Badge, Button, Card, cx, EmptyState, ErrorBox, inputClass, Modal, Notice, SectionTitle, useToast } from "../ui";
import { useProject } from "./context";
import { VideoPlayer } from "./VideoPlayer";

type Choice = "glitch" | "bad" | "reshoot";
const CHOICES: { id: Choice; icon: typeof Zap; emoji: string }[] = [
  { id: "glitch", icon: Zap, emoji: "⚡" },
  { id: "bad", icon: Wand2, emoji: "🪄" },
  { id: "reshoot", icon: Clapperboard, emoji: "🎬" },
];

export function FixTab() {
  const { t, tx } = useI18n();
  const toast = useToast();
  const { id, detail, media, refresh, track, workerOk } = useProject();
  const player = useRef<HTMLVideoElement>(null);
  const [open, setOpen] = useState(false);
  const [at, setAt] = useState(0);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [prompt, setPrompt] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<FixResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [undoing, setUndoing] = useState<string | null>(null);

  const video = mainVideo(media);
  const fixed = detail.project.scenes.filter((s) => s.fixes.length > 0 || s.take > 0);

  const flag = () => {
    const v = player.current;
    if (v) v.pause();
    setAt(round(v?.currentTime ?? 0, 2));
    setChoice(null);
    setPrompt("");
    setResult(null);
    setError(null);
    setOpen(true);
  };

  const send = async () => {
    if (!choice) return;
    const body: FixIn =
      choice === "glitch"
        ? { at, duration: 0.2, mode: "auto" }
        : choice === "bad"
          ? { at, duration: 1.0, mode: "retake", prompt: prompt.trim() || null }
          : { at, mode: "reshoot", prompt: prompt.trim() || null };
    setSending(true);
    setError(null);
    try {
      setResult(await api.addFix(id, body));
      refresh();
    } catch (e) {
      setError(errorText(e, t));
    } finally {
      setSending(false);
    }
  };

  const apply = async () => {
    setApplying(true);
    try {
      track(await api.render(id, { deliveries: ["web"], qa: true }));
      setOpen(false);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError(errorText(e, t));
    } finally {
      setApplying(false);
    }
  };

  const undo = async (sid: string) => {
    setUndoing(sid);
    try {
      await api.undoFix(id, sid);
      toast(t("fix.undone"));
      refresh();
    } catch (e) {
      toast(errorText(e, t), "error");
    } finally {
      setUndoing(null);
    }
  };

  const decision = (r: FixResult) =>
    t(`fix.action.${r.action}` as Key, {
      scene: r.scene,
      a: (r.start ?? 0).toFixed(2),
      b: (r.end ?? 0).toFixed(2),
      take: r.take ?? "",
    });

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
      <div className="flex min-w-0 flex-col gap-4">
        <SectionTitle title={t("fix.title")} hint={t("fix.hint")} />
        {video ? (
          <>
            <VideoPlayer ref={player} src={video} aspect={detail.project.aspect} maxHeight="62vh" />
            <div className="flex justify-center">
              <Button variant="coral" size="xl" onClick={flag} icon={<span aria-hidden>🚩</span>}>
                {t("fix.here")}
              </Button>
            </div>
          </>
        ) : (
          <EmptyState emoji="🎞️" title={t("fix.noVideo")} />
        )}
      </div>

      <aside className="lg:sticky lg:top-24 lg:self-start">
        <Card className="flex flex-col gap-3 p-5">
          <h2 className="text-lg font-bold">{t("fix.list")}</h2>
          {fixed.length === 0 ? (
            <p className="text-sm text-muted">{t("fix.list.empty")}</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {fixed.map((s) => (
                <li key={s.id} className="rounded-xl border border-line p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5 font-semibold">
                      <span aria-hidden>{KIND_META[s.kind].emoji}</span> {s.id}
                    </span>
                    {s.take > 0 && <Badge tone="blue">{t("fix.take", { n: s.take })}</Badge>}
                  </div>
                  {s.fixes.length > 0 && (
                    <>
                      <ul className="mt-2 flex flex-col gap-1 text-xs text-muted">
                        {s.fixes.map((f, i) => (
                          <li key={i} dir="auto">
                            <span className="font-semibold text-ink">{tx(`fix.kind.${f.kind}`, f.kind)}</span> · {f.start.toFixed(2)}–{f.end.toFixed(2)} s
                            {f.prompt ? ` · “${f.prompt}”` : ""}
                          </li>
                        ))}
                      </ul>
                      <Button variant="ghost" size="sm" className="mt-2" loading={undoing === s.id} onClick={() => undo(s.id)} icon={<Undo2 className="size-3.5" />}>
                        {t("fix.undo")}
                      </Button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
          {fixed.some((s) => s.fixes.length > 0) && (
            <Button onClick={apply} loading={applying} disabled={!workerOk} icon={<Sparkles className="size-4" />}>
              {t("fix.apply")}
            </Button>
          )}
        </Card>
      </aside>

      <Modal open={open} onClose={() => setOpen(false)} title={t("fix.what", { t: timecode(at) })} wide>
        {!result ? (
          <div className="flex flex-col gap-4">
            <div role="radiogroup" aria-label={t("fix.what", { t: timecode(at) })} className="grid gap-3 sm:grid-cols-3">
              {CHOICES.map((c) => (
                <button
                  key={c.id}
                  role="radio"
                  aria-checked={choice === c.id}
                  onClick={() => setChoice(c.id)}
                  className={cx(
                    "flex flex-col gap-1.5 rounded-2xl border-2 p-4 text-left transition",
                    choice === c.id ? "border-coral-500 bg-coral-50 ring-4 ring-coral-100" : "border-line hover:border-coral-500/50",
                  )}
                >
                  <span className="text-3xl" aria-hidden>
                    {c.emoji}
                  </span>
                  <span className="font-bold">{t(`fix.${c.id}` as Key)}</span>
                  <span className="text-xs text-muted">{t(`fix.${c.id}.desc` as Key)}</span>
                </button>
              ))}
            </div>
            {(choice === "bad" || choice === "reshoot") && (
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-semibold">
                  {t("fix.prompt")}
                  {choice === "reshoot" && <span className="ml-1.5 font-normal text-muted">({t("common.optional")})</span>}
                </span>
                <textarea
                  dir="auto"
                  rows={3}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder={t("fix.prompt.placeholder")}
                  className={inputClass}
                />
              </label>
            )}
            {error && <ErrorBox error={error} />}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button variant="coral" onClick={send} loading={sending} disabled={!choice}>
                {t("fix.send")}
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <p className="text-sm font-semibold text-muted">{t("fix.decided")}</p>
            <Notice tone={result.action === "none" ? "blue" : "green"} icon={<Info className="size-5" />}>
              <p className="font-semibold">{decision(result)}</p>
              {result.message && (
                <p className="mt-1" dir="auto">
                  {result.message}
                </p>
              )}
            </Notice>
            {error && <ErrorBox error={error} />}
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="secondary" onClick={() => setOpen(false)}>
                {t("common.close")}
              </Button>
              {result.action !== "none" && (
                <Button onClick={apply} loading={applying} disabled={!workerOk} icon={<Sparkles className="size-4" />}>
                  {t("fix.apply")}
                </Button>
              )}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
