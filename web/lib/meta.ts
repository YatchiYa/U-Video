import type { Aspect, Mode, SceneKind } from "./api";

export const MODE_META: Record<Mode, { emoji: string; gradient: string; tone: string }> = {
  ugc: { emoji: "🗣️", gradient: "from-amber-200 via-orange-100 to-rose-100", tone: "bg-orange-100 text-orange-800" },
  influencer: { emoji: "🌟", gradient: "from-fuchsia-200 via-pink-100 to-violet-100", tone: "bg-fuchsia-100 text-fuchsia-800" },
  faceless: { emoji: "🎬", gradient: "from-sky-200 via-cyan-100 to-emerald-100", tone: "bg-sky-100 text-sky-800" },
  promo: { emoji: "📺", gradient: "from-violet-200 via-indigo-100 to-sky-100", tone: "bg-violet-100 text-violet-800" },
};

export const KIND_META: Record<SceneKind, { emoji: string; color: string; block: string }> = {
  shot: { emoji: "🎥", color: "bg-orange-50", block: "bg-orange-400/90 border-orange-500" },
  clip: { emoji: "📼", color: "bg-amber-50", block: "bg-amber-400/90 border-amber-500" },
  image: { emoji: "🖼️", color: "bg-lime-50", block: "bg-lime-500/90 border-lime-600" },
  title: { emoji: "🔤", color: "bg-violet-50", block: "bg-violet-500/90 border-violet-600" },
  screen: { emoji: "📱", color: "bg-sky-50", block: "bg-sky-500/90 border-sky-600" },
  devices: { emoji: "💻", color: "bg-cyan-50", block: "bg-cyan-500/90 border-cyan-600" },
  features: { emoji: "✨", color: "bg-pink-50", block: "bg-pink-500/90 border-pink-600" },
  endcard: { emoji: "🏁", color: "bg-emerald-50", block: "bg-emerald-500/90 border-emerald-600" },
};

/** Tailwind aspect-ratio class for a video format. */
export const ASPECT_CLASS: Record<Aspect, string> = {
  "9:16": "aspect-[9/16]",
  "16:9": "aspect-video",
  "1:1": "aspect-square",
  "4:5": "aspect-[4/5]",
};

export const LENGTH_PRESETS = [15, 20, 30, 45, 60, 90];
