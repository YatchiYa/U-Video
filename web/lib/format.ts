import { ApiError } from "./api";
import type { T } from "./i18n";

/** 75 -> "1:15", 3725 -> "1:02:05" */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(r).padStart(2, "0")}`;
}

/** Timecode with tenths: 12.34 -> "0:12.3" */
export function timecode(seconds: number): string {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}:${r < 10 ? "0" : ""}${r.toFixed(1)}`;
}

/** A rough duration in words: "about 3 min", "about 1 h 20 min", "under a minute". */
export function roughDuration(seconds: number, lang: "fr" | "en"): string {
  const min = Math.round(seconds / 60);
  if (seconds < 60) return lang === "fr" ? "moins d'une minute" : "under a minute";
  if (min < 60) return lang === "fr" ? `environ ${min} min` : `about ${min} min`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return lang === "fr" ? `environ ${h} h ${m ? `${m} min` : ""}`.trim() : `about ${h} h ${m ? `${m} min` : ""}`.trim();
}

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function dateTime(epochSeconds: number, lang: "fr" | "en"): string {
  const d = new Date(epochSeconds * 1000);
  return d.toLocaleString(lang === "fr" ? "fr-FR" : "en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** The readable message of any error (API `detail` messages are shown as they are). */
export function errorText(e: unknown, t: T): string {
  if (e instanceof ApiError) {
    if (e.message === "NETWORK" || e.status === 0) return t("common.network");
    if (e.status === 404 && !e.message) return t("common.notFound");
    return e.message;
  }
  if (e instanceof Error) return e.message;
  return String(e);
}

export function slugify(name: string): string {
  return name.trim().replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60);
}

export const round = (x: number, d = 2) => Math.round(x * 10 ** d) / 10 ** d;

const LANG_CODES: Record<string, string> = {
  arabic: "ar", chinese: "zh", danish: "da", dutch: "nl", english: "en", finnish: "fi", french: "fr", german: "de",
  greek: "el", hebrew: "he", hindi: "hi", italian: "it", japanese: "ja", korean: "ko", malay: "ms", norwegian: "no",
  polish: "pl", portuguese: "pt", russian: "ru", spanish: "es", swahili: "sw", swedish: "sv", turkish: "tr",
};

/** "French" (the API's language names are English) -> "Français" in the French UI. */
export function languageLabel(name: string, lang: "fr" | "en"): string {
  const code = LANG_CODES[name.toLowerCase()];
  if (!code || lang === "en") return name;
  try {
    const s = new Intl.DisplayNames([lang], { type: "language" }).of(code);
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : name;
  } catch {
    return name;
  }
}
