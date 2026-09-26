"use client";

import { AlertTriangle, ChevronLeft, ChevronRight, Maximize2, Music2, Pause, Pin, Play, Plus, RotateCcw, Trash2, ZoomIn, ZoomOut } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import {
  api,
  mainVideo,
  trackOf,
  type AudioClip,
  type MusicClip,
  type TimelineView,
  type VideoClip,
  type VoiceClip,
} from "@/lib/api";
import { errorText, round, timecode } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useI18n, type Key } from "@/lib/i18n";
import { KIND_META } from "@/lib/meta";
import { Badge, Button, Card, cx, ErrorBox, Field, Notice, NumberInput, SectionTitle, Skeleton, useToast } from "../ui";
import { useProject } from "./context";
import { VideoPlayer } from "./VideoPlayer";
import { MixButton } from "./VoiceTab";

type TrackKind = "video" | "voice" | "music" | "audio";
type Sel = { track: TrackKind; id: string } | null;
type Drag = { track: TrackKind; id: string; x0: number; orig: number; dx: number; moved: boolean } | null;

const LABEL_W = 104;
const ROW_H: Record<TrackKind, number> = { video: 60, voice: 52, music: 44, audio: 52 };
const RULER_H = 32;
const ZOOM_MIN = 8;
const ZOOM_MAX = 400;

function tickStep(pps: number): { minor: number; major: number } {
  if (pps >= 160) return { minor: 0.1, major: 1 };
  if (pps >= 60) return { minor: 0.5, major: 1 };
  if (pps >= 25) return { minor: 1, major: 5 };
  if (pps >= 10) return { minor: 1, major: 10 };
  return { minor: 5, major: 30 };
}

// ---------------------------------------------------------------- inspector forms
function VoiceInspector({ clip, onPlace, busy }: { clip: VoiceClip; onPlace: (at: number | null, gain?: number) => void; busy: boolean }) {
  const { t } = useI18n();
  const [gain, setGain] = useState(clip.gain_db);
  return (
    <div className="flex flex-col gap-3">
      <p className="rounded-xl bg-canvas p-3 text-sm" dir="auto">
        “{clip.text}”
      </p>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge tone={clip.manual ? "brand" : "neutral"}>
          {clip.manual && <Pin className="size-3" aria-hidden />}
          {clip.manual ? t("tl.manual") : t("tl.automatic")}
        </Badge>
        <span className="tabular-nums text-muted">
          {timecode(clip.start)} → {timecode(clip.start + clip.dur)}
        </span>
      </div>
      <div className="flex gap-2">
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => onPlace(Math.max(0, round(clip.start - 0.1)))} icon={<ChevronLeft className="size-4" />}>
          {t("tl.earlier")}
        </Button>
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => onPlace(round(clip.start + 0.1))}>
          {t("tl.later")} <ChevronRight className="size-4" aria-hidden />
        </Button>
      </div>
      <Field label={`${t("tl.gain")}: ${gain > 0 ? "+" : ""}${gain} dB`} htmlFor="vgain" hint={clip.manual ? undefined : t("tl.gainNote")}>
        <input id="vgain" type="range" min={-30} max={12} step={0.5} value={gain} onChange={(e) => setGain(Number(e.target.value))} />
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={busy || gain === clip.gain_db} onClick={() => onPlace(clip.start, gain)}>
          {t("tl.apply")}
        </Button>
        {clip.manual && (
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => onPlace(null)} icon={<RotateCcw className="size-3.5" />}>
            {t("tl.auto")}
          </Button>
        )}
      </div>
    </div>
  );
}

function AudioInspector({ clip, url, onPatch, onDelete, busy }: { clip: AudioClip; url: string | null; onPatch: (b: Partial<Record<string, number | boolean | null>>) => void; onDelete: () => void; busy: boolean }) {
  const { t } = useI18n();
  const [f, setF] = useState({
    at: clip.start as number | null,
    trim_start: clip.trim_start as number | null,
    duration: clip.dur,
    gain_db: clip.gain_db,
    fade_in: clip.fade_in as number | null,
    fade_out: clip.fade_out as number | null,
    duck: clip.duck,
  });
  const num = (k: keyof typeof f, label: string, step = 0.1) => (
    <Field label={label} htmlFor={`a-${k}`}>
      <NumberInput id={`a-${k}`} value={f[k] as number | null} step={step} min={0} onChange={(v) => setF({ ...f, [k]: v })} />
    </Field>
  );
  return (
    <div className="flex flex-col gap-3">
      <p className="truncate text-xs text-muted" title={clip.file}>
        {clip.file.split("/").pop()}
      </p>
      {url && <audio controls preload="none" src={url} className="h-9 w-full" />}
      <div className="grid grid-cols-2 gap-3">
        {num("at", t("tl.start"))}
        {num("trim_start", t("tl.trim"))}
        {num("fade_in", t("tl.fadeIn"))}
        {num("fade_out", t("tl.fadeOut"))}
      </div>
      {num("duration", t("tl.duration"))}
      <Field label={`${t("tl.gain")}: ${f.gain_db > 0 ? "+" : ""}${f.gain_db} dB`} htmlFor="a-gain">
        <input id="a-gain" type="range" min={-40} max={12} step={0.5} value={f.gain_db} onChange={(e) => setF({ ...f, gain_db: Number(e.target.value) })} />
      </Field>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={f.duck} onChange={(e) => setF({ ...f, duck: e.target.checked })} className="size-4" />
        {t("tl.duck")}
      </label>
      <div className="flex flex-wrap justify-between gap-2">
        <Button size="sm" disabled={busy} onClick={() => onPatch(f)}>
          {t("tl.apply")}
        </Button>
        <Button size="sm" variant="danger" disabled={busy} onClick={onDelete} icon={<Trash2 className="size-3.5" />}>
          {t("tl.remove")}
        </Button>
      </div>
    </div>
  );
}

function MusicInspector({ clip, onSet, busy }: { clip: MusicClip; onSet: (b: Record<string, number | null>) => void; busy: boolean }) {
  const { t } = useI18n();
  const [f, setF] = useState({ start: clip.start as number | null, offset: clip.offset as number | null, gain_db: clip.gain_db, fade_in: clip.fade_in as number | null, fade_out: clip.fade_out as number | null });
  const num = (k: "start" | "offset" | "fade_in" | "fade_out", label: string) => (
    <Field label={label} htmlFor={`m-${k}`}>
      <NumberInput id={`m-${k}`} value={f[k]} min={0} onChange={(v) => setF({ ...f, [k]: v })} />
    </Field>
  );
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3">
        {num("start", t("tl.start"))}
        {num("offset", t("tl.offset"))}
        {num("fade_in", t("tl.fadeIn"))}
        {num("fade_out", t("tl.fadeOut"))}
      </div>
      <Field label={`${t("tl.gain")}: ${f.gain_db > 0 ? "+" : ""}${f.gain_db} dB`} htmlFor="m-gain">
        <input id="m-gain" type="range" min={-30} max={12} step={0.5} value={f.gain_db} onChange={(e) => setF({ ...f, gain_db: Number(e.target.value) })} />
      </Field>
      <Button size="sm" disabled={busy} onClick={() => onSet(f)}>
        {t("tl.apply")}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------- the editor
export function TimelineTab() {
  const { t, tx } = useI18n();
  const toast = useToast();
  const { id, detail, media, version, refresh } = useProject();
  const tlData = useData(`timeline:${id}`, () => api.timeline(id), version);
  const tl: TimelineView | undefined = tlData.data;

  const player = useRef<HTMLVideoElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const addInput = useRef<HTMLInputElement>(null);
  const [width, setWidth] = useState(800);
  const [zoom, setZoom] = useState<number | null>(null); // px per second; null = fit
  const [playhead, setPlayhead] = useState(0);
  const [sel, setSel] = useState<Sel>(null);
  const [drag, setDrag] = useState<Drag>(null);
  const [pending, setPending] = useState<{ id: string; start: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [changed, setChanged] = useState(false);
  const [scrub, setScrub] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [fileDur, setFileDur] = useState<Record<string, number>>({});

  const video = mainVideo(media);
  /** A server path inside this project -> its URL (GET /api/projects/{id}/files/...). */
  const fileUrl = useCallback(
    (abs: string) => {
      const i = abs.lastIndexOf(`/${id}/`);
      return i < 0 ? null : `/api/projects/${encodeURIComponent(id)}/files/${abs.slice(i + id.length + 2)}`;
    },
    [id],
  );

  // play / pause state of the player (for the toolbar button)
  useEffect(() => {
    const v = player.current;
    if (!v) return;
    const on = () => setPlaying(!v.paused);
    v.addEventListener("play", on);
    v.addEventListener("pause", on);
    v.addEventListener("ended", on);
    return () => {
      v.removeEventListener("play", on);
      v.removeEventListener("pause", on);
      v.removeEventListener("ended", on);
    };
  }, [video, tl !== undefined]); // eslint-disable-line react-hooks/exhaustive-deps -- re-attach when the player appears

  // real length of sounds without an explicit duration (read from the file itself)
  useEffect(() => {
    if (!tl) return;
    for (const c of trackOf(tl, "audio")) {
      if (c.dur !== null || c.file_seconds || c.file in fileDur) continue; // the API already gives the length
      const url = c.url ?? fileUrl(c.file);
      if (!url) continue;
      const a = new Audio();
      a.preload = "metadata";
      a.onloadedmetadata = () => Number.isFinite(a.duration) && setFileDur((m) => ({ ...m, [c.file]: a.duration }));
      a.src = url;
    }
  }, [tl, fileDur, fileUrl]);
  const total = tl?.total ?? 1;
  const fitPps = Math.max(ZOOM_MIN, (width - 32) / Math.max(total, 0.5));
  const pps = zoom ?? fitPps;
  const contentW = Math.max(width - 2, total * pps + 32);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, [tl !== undefined]); // eslint-disable-line react-hooks/exhaustive-deps -- attach once the scroller exists

  // keep the playhead visible while playing
  useEffect(() => {
    const el = scroller.current;
    if (!el || drag) return;
    const x = playhead * pps;
    if (x < el.scrollLeft || x > el.scrollLeft + el.clientWidth - 40) el.scrollLeft = Math.max(0, x - 80);
  }, [playhead, pps, drag]);

  const seek = useCallback(
    (sec: number) => {
      const s = Math.min(Math.max(0, sec), total);
      setPlayhead(s);
      if (player.current) player.current.currentTime = s;
    },
    [total],
  );

  // ------------------------------------------------------------ mutations (the API answers with the new timeline)
  const mutate = async (fn: () => Promise<TimelineView | unknown>, opts: { revertId?: string; ok?: string } = {}) => {
    setBusy(true);
    setError(null);
    try {
      const res = await fn();
      if (res && typeof res === "object" && "tracks" in res) tlData.setData(res as TimelineView);
      setChanged(true);
      if (opts.ok) toast(opts.ok);
      refresh();
    } catch (e) {
      const msg = errorText(e, t); // e.g. "the voice line pinned at 3.2s ends after the end of the video"
      setError(msg);
      toast(msg, "error");
    } finally {
      setPending(null);
      setBusy(false);
    }
  };

  const moveTo = (track: TrackKind, cid: string, start: number) => {
    const at = round(Math.max(0, start), 2);
    setPending({ id: `${track}:${cid}`, start: at });
    if (track === "voice") return mutate(() => api.placeVoice(id, cid, at), { ok: t("tl.moved") });
    if (track === "audio") return mutate(() => api.patchAudio(id, cid, { at }), { ok: t("tl.moved") });
    if (track === "music") return mutate(() => api.setMusic(id, { start: at }), { ok: t("tl.moved") });
  };

  const addSound = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const clip = await api.addAudio(id, file, { at: round(playhead, 2) });
      setSel({ track: "audio", id: clip.id });
      setChanged(true);
      tlData.reload();
      refresh();
    } catch (e) {
      setError(errorText(e, t));
    } finally {
      setBusy(false);
      if (addInput.current) addInput.current.value = "";
    }
  };

  // ------------------------------------------------------------ dragging
  const onDown = (e: PointerEvent<HTMLElement>, track: TrackKind, cid: string, start: number) => {
    setSel({ track, id: cid });
    if (track === "video" || busy || e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    setDrag({ track, id: cid, x0: e.clientX, orig: start, dx: 0, moved: false });
  };
  const onMove = (e: PointerEvent<HTMLElement>) => {
    if (!drag) return;
    const dx = e.clientX - drag.x0;
    setDrag({ ...drag, dx, moved: drag.moved || Math.abs(dx) > 3 });
  };
  const onUp = () => {
    if (!drag) return;
    const d = drag;
    setDrag(null);
    if (d.moved) moveTo(d.track, d.id, d.orig + d.dx / pps);
  };
  const onKey = (e: KeyboardEvent<HTMLElement>, track: TrackKind, cid: string, start: number) => {
    if (track === "video") return;
    const step = e.shiftKey ? 1 : 0.1;
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      moveTo(track, cid, start - step);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      moveTo(track, cid, start + step);
    }
  };
  const posOf = (track: TrackKind, cid: string, start: number) => {
    if (drag && drag.track === track && drag.id === cid) return Math.max(0, drag.orig + drag.dx / pps);
    if (pending && pending.id === `${track}:${cid}`) return pending.start;
    return start;
  };

  // ------------------------------------------------------------ ruler scrubbing
  const rulerTime = (e: PointerEvent<HTMLElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return (e.clientX - r.left) / pps;
  };

  if (tlData.error !== undefined && !tl) {
    return (
      <div className="flex flex-col gap-4">
        <SectionTitle title={t("tl.title")} hint={t("tl.hint")} />
        <ErrorBox error={errorText(tlData.error, t)} onRetry={tlData.reload} />
      </div>
    );
  }
  if (!tl) return <Skeleton className="h-96" />;

  const videoClips = trackOf(tl, "video");
  const voiceClips = trackOf(tl, "voice");
  const musicClips = trackOf(tl, "music");
  const audioClips = trackOf(tl, "audio");
  const { minor, major } = tickStep(pps);
  const ticks: number[] = [];
  for (let k = 0; k * minor <= total + 1e-6; k++) ticks.push(round(k * minor, 3));

  const selVoice = sel?.track === "voice" ? voiceClips.find((c) => c.id === sel.id) : undefined;
  const selAudio = sel?.track === "audio" ? audioClips.find((c) => c.id === sel.id) : undefined;
  const selMusic = sel?.track === "music" ? musicClips[0] : undefined;
  const selVideo = sel?.track === "video" ? videoClips.find((c) => c.id === sel.id) : undefined;

  const block = (track: TrackKind, cid: string, start: number, dur: number | null, cls: string, children: ReactNode, title: string) => {
    const s = posOf(track, cid, start);
    const d = dur ?? Math.max(0.3, total - s);
    const selected = sel?.track === track && sel.id === cid;
    const dragging = drag?.track === track && drag.id === cid && drag.moved;
    return (
      <button
        key={`${track}:${cid}`}
        type="button"
        title={title}
        aria-label={`${title} · ${timecode(s)}`}
        aria-pressed={selected}
        onPointerDown={(e) => onDown(e, track, cid, start)}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={() => setDrag(null)}
        onKeyDown={(e) => onKey(e, track, cid, start)}
        className={cx(
          "absolute top-1.5 bottom-1.5 flex items-center overflow-hidden rounded-lg border px-2 text-left text-xs font-semibold text-white shadow-sm transition-shadow",
          cls,
          track === "video" ? "cursor-pointer" : "cursor-grab touch-none active:cursor-grabbing",
          selected && "ring-[3px] ring-ink/80 ring-offset-1",
          dragging && "z-20 opacity-90 shadow-[var(--shadow-lift)]",
          dur === null && "rounded-r-none border-r-2 border-dashed",
        )}
        style={{ left: s * pps, width: Math.max(6, d * pps) }}
      >
        {children}
      </button>
    );
  };

  const rows: { kind: TrackKind; label: Key; content: ReactNode; empty?: string }[] = [
    {
      kind: "video",
      label: "tl.track.video",
      content: videoClips.map((c: VideoClip) =>
        block(
          "video",
          c.id,
          c.start,
          c.dur,
          KIND_META[c.kind].block,
          <>
            {c.transition_s > 0 && (
              <span className="absolute inset-y-0 left-0 bg-gradient-to-r from-white/50 to-transparent" style={{ width: c.transition_s * pps }} aria-hidden />
            )}
            <span className="relative truncate" dir="auto">
              <span aria-hidden>{KIND_META[c.kind].emoji}</span> {c.label || c.id}
            </span>
          </>,
          `${tx(`kind.${c.kind}`, c.kind)} · ${c.id}`,
        ),
      ),
    },
    {
      kind: "voice",
      label: "tl.track.voice",
      empty: voiceClips.length ? undefined : t("tl.noVoice"),
      content: voiceClips.map((c) =>
        block(
          "voice",
          c.id,
          c.start,
          c.dur,
          c.manual ? "bg-brand-600 border-brand-800" : "bg-brand-400 border-brand-500 border-dashed",
          <span className="flex min-w-0 items-center gap-1">
            {c.manual && <Pin className="size-3 shrink-0" aria-hidden />}
            <span className="truncate" dir="auto">
              {c.text}
            </span>
          </span>,
          `${t("tl.selected.voice", { id: c.id })}`,
        ),
      ),
    },
    {
      kind: "music",
      label: "tl.track.music",
      empty: musicClips.length ? undefined : t("tl.noMusic"),
      content: musicClips.map((c) =>
        block(
          "music",
          c.id,
          c.start,
          c.dur,
          "bg-teal-500 border-teal-600",
          <>
            <span className="absolute inset-y-0 left-0 bg-gradient-to-r from-teal-900/40 to-transparent" style={{ width: c.fade_in * pps }} aria-hidden />
            <span className="absolute inset-y-0 right-0 bg-gradient-to-l from-teal-900/40 to-transparent" style={{ width: c.fade_out * pps }} aria-hidden />
            <span className="relative flex items-center gap-1 truncate">
              <Music2 className="size-3.5" aria-hidden /> {t("tl.selected.music")} {c.gain_db ? `· ${c.gain_db} dB` : ""}
            </span>
          </>,
          t("tl.selected.music"),
        ),
      ),
    },
    {
      kind: "audio",
      label: "tl.track.audio",
      empty: audioClips.length ? undefined : t("tl.noAudio"),
      content: audioClips.map((c) =>
        block(
          "audio",
          c.id,
          c.start,
          c.dur ?? ((c.file_seconds ?? fileDur[c.file]) !== undefined
            ? Math.max(0.1, (c.file_seconds ?? fileDur[c.file]) - c.trim_start) : null),
          "bg-amber-500 border-amber-600",
          <span className="truncate">
            🔊 {c.id}
            {c.dur === null && (c.file_seconds ?? fileDur[c.file]) === undefined ? ` · ${t("tl.untilEnd")}` : ""}
          </span>,
          t("tl.selected.audio", { id: c.id }),
        ),
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-6">
      <SectionTitle title={t("tl.title")} hint={t("tl.hint")} />

      <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <div className="order-1 flex min-w-0 flex-col gap-3">
          {video ? (
            <VideoPlayer ref={player} src={video} aspect={detail.project.aspect} onTime={setPlayhead} maxHeight="44vh" />
          ) : (
            <Notice tone="blue">{t("fix.noVideo")}</Notice>
          )}
          {tl.missing_voice.length > 0 && <Notice tone="amber">{t("tl.missing", { ids: tl.missing_voice.join(", ") })}</Notice>}
          {tl.warnings.length > 0 && (
            <Notice tone="amber" icon={<AlertTriangle className="size-5 text-amber-600" />}>
              <p className="font-semibold">{t("tl.warnings")}</p>
              <ul className="mt-1 list-disc pl-5" dir="auto">
                {tl.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </Notice>
          )}
        </div>
        <aside className="order-3 flex flex-col gap-4 lg:order-2">
          <Card className="flex flex-col gap-3 p-5">
            <h2 className="text-lg font-bold">
              {selVoice
                ? t("tl.selected.voice", { id: selVoice.id })
                : selAudio
                  ? t("tl.selected.audio", { id: selAudio.id })
                  : selMusic
                    ? t("tl.selected.music")
                    : selVideo
                      ? t("tl.selected.video", { id: selVideo.id })
                      : t("tl.title")}
            </h2>
            {!sel && <p className="text-sm text-muted">{t("tl.select")}</p>}
            {selVoice && <VoiceInspector key={`${selVoice.id}:${selVoice.start}:${selVoice.gain_db}`} clip={selVoice} busy={busy} onPlace={(at, gain) => mutate(() => api.placeVoice(id, selVoice.id, at, gain))} />}
            {selAudio && (
              <AudioInspector
                key={JSON.stringify(selAudio)}
                clip={selAudio}
                url={selAudio.url ?? fileUrl(selAudio.file)}
                busy={busy}
                onPatch={(b) => mutate(() => api.patchAudio(id, selAudio.id, b))}
                onDelete={() => {
                  setSel(null);
                  mutate(() => api.deleteAudio(id, selAudio.id));
                }}
              />
            )}
            {selMusic && <MusicInspector key={JSON.stringify(selMusic)} clip={selMusic} busy={busy} onSet={(b) => mutate(() => api.setMusic(id, b))} />}
            {selVideo && (
              <div className="flex flex-col gap-2 text-sm">
                <p dir="auto" className="font-semibold">
                  {KIND_META[selVideo.kind].emoji} {selVideo.label}
                </p>
                <p className="tabular-nums text-muted">
                  {timecode(selVideo.start)} → {timecode(selVideo.start + selVideo.dur)} · {selVideo.dur.toFixed(2)} s
                  {selVideo.stretch !== 1 ? ` · ×${selVideo.stretch}` : ""}
                </p>
                <p className="text-muted">{t("tl.video.readonly")}</p>
              </div>
            )}
            {error && <ErrorBox error={error} />}
          </Card>
          <MixButton highlight={changed} />
        </aside>

      <Card className="order-2 min-w-0 overflow-hidden lg:order-3 lg:col-span-2">
        {/* toolbar */}
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-canvas/50 px-3 py-2">
          <Button
            variant="primary"
            size="sm"
            disabled={!video}
            aria-label={playing ? t("tl.pause") : t("tl.play")}
            onClick={() => {
              const v = player.current;
              if (v) void (v.paused ? v.play() : v.pause());
            }}
          >
            {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
          </Button>
          <span className="rounded-lg bg-ink px-2.5 py-1 font-mono text-sm tabular-nums text-white" aria-label={t("tl.playhead")}>
            {timecode(playhead)} / {timecode(total)}
          </span>
          <div className="ml-auto flex items-center gap-1.5">
            <Button variant="ghost" size="sm" aria-label={t("tl.zoomOut")} onClick={() => setZoom(Math.max(ZOOM_MIN, pps / 1.5))}>
              <ZoomOut className="size-4" />
            </Button>
            <input
              type="range"
              aria-label={t("tl.zoom")}
              min={Math.log(ZOOM_MIN)}
              max={Math.log(ZOOM_MAX)}
              step={0.01}
              value={Math.log(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, pps)))}
              onChange={(e) => setZoom(Math.exp(Number(e.target.value)))}
              className="w-28 sm:w-40"
            />
            <Button variant="ghost" size="sm" aria-label={t("tl.zoomIn")} onClick={() => setZoom(Math.min(ZOOM_MAX, pps * 1.5))}>
              <ZoomIn className="size-4" />
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setZoom(null)} icon={<Maximize2 className="size-3.5" />}>
              {t("tl.fit")}
            </Button>
          </div>
          <Button size="sm" variant="soft" loading={busy && !drag && !pending} onClick={() => addInput.current?.click()} icon={<Plus className="size-4" />} title={t("tl.add.hint", { t: timecode(playhead) })}>
            {t("tl.add")}
          </Button>
          <input ref={addInput} type="file" accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg,.flac" hidden onChange={(e) => addSound(e.target.files?.[0])} />
        </div>

        <div className="flex">
          {/* track labels */}
          <div className="shrink-0 border-r border-line bg-surface" style={{ width: LABEL_W }}>
            <div style={{ height: RULER_H }} className="border-b border-line" />
            {rows.map((r) => (
              <div key={r.kind} style={{ height: ROW_H[r.kind] }} className="flex items-center border-b border-line/70 px-3 text-xs font-bold uppercase tracking-wide text-muted">
                {t(r.label)}
              </div>
            ))}
          </div>
          {/* scrollable area */}
          <div ref={scroller} className="relative min-w-0 flex-1 overflow-x-auto overflow-y-hidden">
            <div className="relative" style={{ width: contentW }}>
              {/* ruler: click / drag to seek */}
              <div
                role="slider"
                tabIndex={0}
                aria-label={t("tl.playhead")}
                aria-valuemin={0}
                aria-valuemax={total}
                aria-valuenow={round(playhead, 1)}
                aria-valuetext={timecode(playhead)}
                className="relative cursor-pointer touch-none select-none border-b border-line bg-canvas/60"
                style={{ height: RULER_H }}
                onPointerDown={(e) => {
                  e.currentTarget.setPointerCapture(e.pointerId);
                  setScrub(true);
                  seek(rulerTime(e));
                }}
                onPointerMove={(e) => scrub && seek(rulerTime(e))}
                onPointerUp={() => setScrub(false)}
                onKeyDown={(e) => {
                  if (e.key === "ArrowLeft") seek(playhead - (e.shiftKey ? 1 : 0.1));
                  if (e.key === "ArrowRight") seek(playhead + (e.shiftKey ? 1 : 0.1));
                  if (e.key === "Home") seek(0);
                  if (e.key === "End") seek(total);
                }}
              >
                {ticks.map((x) => {
                  const isMajor = Math.abs(x / major - Math.round(x / major)) < 1e-6;
                  return (
                    <div key={x} className="absolute bottom-0" style={{ left: x * pps }}>
                      <div className={cx("w-px", isMajor ? "h-3 bg-ink/40" : "h-1.5 bg-ink/20")} />
                      {isMajor && <span className="absolute bottom-3 left-1 whitespace-nowrap text-[10px] tabular-nums text-muted">{timecode(x).replace(/\.0$/, "")}</span>}
                    </div>
                  );
                })}
                <div className="absolute inset-y-0 bg-ink/5" style={{ left: total * pps, right: 0 }} aria-hidden />
              </div>
              {/* tracks */}
              {rows.map((r) => (
                <div key={r.kind} className={cx("relative border-b border-line/70", r.kind === "video" ? "bg-ink/[0.02]" : "")} style={{ height: ROW_H[r.kind] }}>
                  <div className="absolute inset-y-0 bg-ink/5" style={{ left: total * pps, right: 0 }} aria-hidden />
                  {r.content}
                  {r.empty && <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-muted">{r.empty}</span>}
                </div>
              ))}
              {/* playhead */}
              <div className="pointer-events-none absolute top-0 bottom-0 z-30 w-0.5 bg-coral-500" style={{ left: playhead * pps }} aria-hidden>
                <div className="absolute -left-[5px] top-0 size-3 rounded-full bg-coral-500 shadow" />
              </div>
            </div>
          </div>
        </div>
      </Card>
      </div>
    </div>
  );
}
