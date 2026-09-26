/**
 * Typed client for the UGC Studio API (docs/openapi.json; shapes checked against src/ugc_studio/api.py,
 * service.py, timeline.py and jobs.py). Every call goes to the relative /api/... path, proxied by Next.
 * One place for fetch + error handling: failures throw ApiError with a readable message.
 */

// ====================================================================== enums
export type Mode = "ugc" | "influencer" | "faceless" | "promo";
export type Aspect = "9:16" | "16:9" | "1:1" | "4:5";
export type Quality = "draft" | "standard" | "high" | "tv";
export type SceneKind = "shot" | "clip" | "image" | "title" | "screen" | "devices" | "features" | "endcard";
export type VoiceEngine = "auto" | "qwen" | "chatterbox" | "habibi" | "elevenlabs" | "openai" | "gemini";
export type Dialect = "MSA" | "ALG" | "EGY" | "IRQ" | "MAR";
export type ExportFormat = "tv" | "web" | "vertical" | "square" | "portrait" | "cover";
export type FixMode = "auto" | "interpolate" | "freeze" | "retake" | "reshoot";
export type JobKind = "render" | "mix" | "create" | "persona" | "image" | "export" | "qa" | "site" | "preview";
export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export const TERMINAL: JobStatus[] = ["done", "failed", "cancelled"];
export const VOICE_ENGINES: VoiceEngine[] = ["auto", "qwen", "chatterbox", "habibi", "elevenlabs", "openai", "gemini"];
export const DIALECTS: Dialect[] = ["MSA", "ALG", "EGY", "IRQ", "MAR"];

// ====================================================================== system
export interface Health {
  ok: boolean;
  store: string;
  store_ok: boolean;
  worker: boolean;
  gpu: string | null;
  outputs: string;
  time: number;
}

export interface Catalog {
  modes: { id: Mode; description: string }[];
  styles: string[];
  aspects: Aspect[];
  qualities: Quality[];
  languages: string[];
  dialects: Dialect[];
  transitions: string[];
  icons: string[];
  export_formats: ExportFormat[];
}

export interface ProviderRow {
  kind: "image" | "video" | "voice" | "music";
  provider: string;
  model: string | null;
  source: string;
  keys: Record<string, boolean>;
  available: string[];
}

export interface Upload {
  ref: string;
  name: string;
  size: number;
}

export interface Persona {
  name: string;
  description: string;
  language: string;
  images: string[];
  /** GET /api/personas/{name}/files/{image} */
  image_urls?: string[];
}

// ====================================================================== project model (schema.py)
export interface Transition {
  type: string;
  seconds: number;
}

export interface Fix {
  kind: "interpolate" | "retake" | "freeze";
  start: number;
  end: number;
  prompt?: string | null;
  seed?: number | null;
  video?: boolean;
  audio?: boolean;
}

export interface Feature {
  title: string;
  subtitle?: string;
  icon?: string;
}

export interface Scene {
  id: string;
  kind: SceneKind;
  seconds: number;
  prompt: string;
  dialogue: string | null;
  continuity: "cut" | "match" | "continue";
  start_image: string | null;
  start_prompt: string | null;
  end_image: string | null;
  end_prompt: string | null;
  characters: string[];
  products: string[];
  clip_in: number;
  screen_insert: Record<string, unknown> | null;
  seed: number | null;
  take: number;
  fixes: Fix[];
  voiceover: string | null;
  voice_take: number;
  caption: string[];
  transition: Transition;
  ambience: number;
  video: string | null;
  image: string | null;
  url: string | null;
  device: "phone" | "laptop" | "none";
  reveal: "rise" | "spin" | "flip";
  theme: "auto" | "light" | "dark";
  devices: { url?: string | null; image?: string | null; label?: string }[];
  headline: string | null;
  eyebrow: string | null;
  bullets: string[];
  features: Feature[];
  offer: string | null;
}

export interface Brand {
  name: string;
  tagline: string;
  url: string;
  phone: string;
  offer: string;
  logo: string | null;
  primary: string;
  secondary: string;
  dark: string;
  light: string;
  accent: string;
  font_heading: string;
  font_body: string;
}

export interface Project {
  title: string;
  mode: Mode;
  style: string;
  aspect: Aspect;
  quality: Quality;
  fps: number;
  language: string;
  seed: number;
  target_seconds: number | null;
  source_url: string | null;
  look: string;
  pronounce: Record<string, string>;
  voice_style: string;
  brand: Brand;
  characters: { id: string; description: string; images: string[]; persona: string | null }[];
  products: { id: string; description: string; images: string[] }[];
  voice: {
    enabled: boolean;
    description: string;
    engine: VoiceEngine;
    model: string | null;
    voice_id: string | null;
    dialect: Dialect | null;
    file: string | null;
    tempo: number;
    [k: string]: unknown;
  };
  providers: Record<string, string | null>;
  edit: {
    voice: Record<string, { at: number; gain_db: number }>;
    audio: AudioClipModel[];
    music: { start: number; offset: number; gain_db: number; fade_in: number; fade_out: number };
  };
  music: { mode: "generate" | "file" | "none"; prompt: string; file: string | null; volume: number; bpm: number | null };
  captions: { enabled: boolean; style: string; position: string };
  scenes: Scene[];
  [k: string]: unknown;
}

export interface AudioClipModel {
  id: string;
  file: string;
  at: number;
  trim_start: number;
  duration: number | null;
  gain_db: number;
  fade_in: number;
  fade_out: number;
  duck: boolean;
}

// ====================================================================== project views
export interface ProjectSummary {
  id: string;
  path: string;
  title?: string;
  mode?: Mode;
  aspect?: Aspect;
  language?: string;
  scenes?: number;
  video?: string | null;
  video_url?: string | null;
  updated?: number;
  error?: string; // a broken project is listed with its error
}

export interface SceneStatus {
  id: string;
  kind: SceneKind;
  start: number | null;
  dur: number | null;
  keyframe: boolean | null;
  video: boolean | null;
  voice: boolean | null;
  fixes: number;
  text: string | null;
}

export interface ProjectStatus {
  title: string;
  mode: Mode;
  scenes: SceneStatus[];
  outputs: string[];
  total: number | null;
}

export interface ProjectDetail {
  id: string;
  project: Project;
  status: ProjectStatus;
}

export interface PlanItem {
  stage: string;
  key: string;
  what: string;
  seconds: number;
}

export interface Plan {
  items: PlanItem[];
  total_seconds: number;
  errors: string[];
  warnings: string[];
}

export interface Media {
  outputs: { name: string; url: string; size: number }[];
  thumbnails: Record<string, string>;
  keyframes: Record<string, string>;
  contact_sheet: string | null;
}

export interface VoiceLine {
  id: string;
  text: string;
  take: number;
  score: number | null;
  mos: number | null;
  quality?: number | null; // not sent by the API today; shown when present
  seconds: number | null;
  heard: string | null;
  stale: boolean;
  pinned_at: number | null;
}

export interface VoiceView {
  engine: string;
  voice_id: string | null;
  file: string | null;
  lines: VoiceLine[];
}

// ====================================================================== timeline (timeline.tracks)
export interface VideoClip {
  id: string;
  kind: SceneKind;
  start: number;
  dur: number;
  transition: string;
  transition_s: number;
  label: string;
  stretch: number;
}

export interface VoiceClip {
  id: string;
  start: number;
  dur: number;
  text: string;
  manual: boolean;
  gain_db: number;
}

export interface MusicClip {
  id: "music";
  start: number;
  dur: number;
  offset: number;
  gain_db: number;
  fade_in: number;
  fade_out: number;
  manual: boolean;
}

export interface AudioClip {
  id: string;
  file: string;
  start: number;
  dur: number | null;
  trim_start: number;
  gain_db: number;
  fade_in: number;
  fade_out: number;
  duck: boolean;
  manual: boolean;
  /** playable URL of the sound (GET /api/projects/{id}/files/...) */
  url?: string | null;
  /** real length of the file, seconds */
  file_seconds?: number | null;
}

export type Track =
  | { id: "video"; kind: "video"; clips: VideoClip[] }
  | { id: "voice"; kind: "voice"; clips: VoiceClip[] }
  | { id: "music"; kind: "music"; clips: MusicClip[] }
  | { id: "audio"; kind: "audio"; clips: AudioClip[] };

export interface TimelineView {
  fps: number;
  total: number;
  tracks: Track[];
  warnings: string[];
  missing_voice: string[];
}

export function trackOf<K extends Track["kind"]>(tl: TimelineView, kind: K): Extract<Track, { kind: K }>["clips"] {
  const t = tl.tracks.find((x) => x.kind === kind) as Extract<Track, { kind: K }> | undefined;
  return (t?.clips ?? []) as never;
}

// ====================================================================== fixes
export interface FixResult {
  scene: string;
  action: "none" | "reshoot" | "interpolate" | "freeze" | "retake";
  kind?: string;
  message?: string;
  take?: number;
  seed?: number | null;
  start?: number;
  end?: number;
  local?: number;
}

// ====================================================================== jobs
export interface QaIssue {
  level: "fail" | "warn";
  check: string;
  detail: string;
}

export interface QaReport {
  verdict: "PASS" | "WARN" | "FAIL";
  duration_s: number;
  width: number;
  height: number;
  issues: QaIssue[];
  [k: string]: unknown;
}

export interface RenderResult {
  deliveries: Record<string, string>;
  total: number;
  warnings: string[];
  seconds: number;
  qa?: QaReport;
}

export interface SiteResult {
  brand: Brand;
  title: string | null;
  sections: string[];
  ctas: string[];
  pages: number;
  folder: string;
}

export interface Job<R = unknown> {
  id: string;
  kind: JobKind;
  project: string | null;
  params: Record<string, unknown>;
  queue: "gpu" | "light";
  status: JobStatus;
  created: number;
  started: number | null;
  finished: number | null;
  stage: string | null;
  message: string | null;
  result: R | null;
  error: string | null;
  events: number;
  position?: number | null;
}

export interface JobEvent {
  event: "queued" | "started" | "progress" | "log" | "done" | "failed" | "cancelled" | string;
  t: number;
  stage?: string;
  message?: string;
}

// ====================================================================== request bodies
export interface CreateIn {
  name: string;
  mode: Mode;
  brief: string;
  seconds?: number;
  aspect?: Aspect;
  quality?: Quality;
  language?: string;
  url?: string | null;
  persona?: string | null;
  face_uploads?: string[];
  product?: string | null;
  product_uploads?: string[];
  style?: string | null;
  seed?: number;
}

export interface FixIn {
  at?: number | null;
  duration?: number;
  mode?: FixMode;
  prompt?: string | null;
  seed?: number | null;
  scene?: string | null;
}

export interface AudioPatch {
  at?: number | null;
  trim_start?: number | null;
  duration?: number | null;
  gain_db?: number | null;
  fade_in?: number | null;
  fade_out?: number | null;
  duck?: boolean | null;
}

export interface MusicIn {
  start?: number | null;
  offset?: number | null;
  gain_db?: number | null;
  fade_in?: number | null;
  fade_out?: number | null;
}

// ====================================================================== fetch + errors
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

/** FastAPI errors: {detail: "text"} or {detail: [{loc, msg}]} (422 validation). */
function readableDetail(body: unknown): string | null {
  if (!body || typeof body !== "object" || !("detail" in body)) return null;
  const d = (body as { detail: unknown }).detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d
      .map((e) => {
        const loc = Array.isArray(e?.loc) ? e.loc.filter((x: unknown) => x !== "body").join(" › ") : "";
        return loc ? `${loc}: ${e?.msg ?? ""}` : String(e?.msg ?? "");
      })
      .join("\n");
  }
  return JSON.stringify(d);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, cache: "no-store", headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["content-type"] = "application/json";
  }
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, "NETWORK");
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const msg = readableDetail(data) ?? (typeof data === "string" && data.length < 300 ? data : "");
    // 500 from the proxy with an empty body = the API server is not reachable
    throw new ApiError(res.status, msg || (res.status >= 500 ? "NETWORK" : `HTTP ${res.status}`));
  }
  return data as T;
}

const get = <T>(p: string) => request<T>("GET", p);
const post = <T>(p: string, b?: unknown) => request<T>("POST", p, b ?? {});
const put = <T>(p: string, b: unknown) => request<T>("PUT", p, b);
const patch = <T>(p: string, b: unknown) => request<T>("PATCH", p, b);
const del = <T>(p: string) => request<T>("DELETE", p);
const P = (pid: string) => `/api/projects/${encodeURIComponent(pid)}`;
const E = encodeURIComponent;

// ====================================================================== endpoints
export const api = {
  health: () => get<Health>("/api/health"),
  catalog: () => get<Catalog>("/api/catalog"),
  providers: () => get<ProviderRow[]>("/api/providers"),

  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return post<Upload>("/api/uploads", fd);
  },
  personas: () => get<Persona[]>("/api/personas"),
  analyzeSite: (url: string) => post<Job<SiteResult>>("/api/site", { url }),

  projects: () => get<ProjectSummary[]>("/api/projects"),
  createProject: (body: CreateIn) => post<Job<{ id: string; title: string; scenes: number }>>("/api/projects", body),
  importProject: (name: string, project: unknown) => post<{ id: string }>("/api/projects/import", { name, project }),
  project: (pid: string) => get<ProjectDetail>(P(pid)),
  saveProject: (pid: string, project: Project) =>
    put<{ id: string; title: string; scenes: number }>(P(pid), project),
  deleteProject: (pid: string) => del<{ id: string; moved_to: string }>(P(pid)),
  plan: (pid: string) => get<Plan>(`${P(pid)}/plan`),
  status: (pid: string) => get<ProjectStatus>(`${P(pid)}/status`),
  media: (pid: string) => get<Media>(`${P(pid)}/media`),
  projectProviders: (pid: string) => get<ProviderRow[]>(`${P(pid)}/providers`),

  render: (pid: string, body: { deliveries?: ("web" | "tv")[]; only?: string[] | null; qa?: boolean } = {}) =>
    post<Job<RenderResult>>(`${P(pid)}/render`, { deliveries: ["web"], qa: true, ...body }),
  mix: (pid: string) => post<Job<RenderResult>>(`${P(pid)}/mix`),
  exportVideo: (pid: string, format: ExportFormat, at = 0) =>
    post<Job<{ file: string }>>(`${P(pid)}/export`, { format, at: Math.max(0, at) }),
  qa: (pid: string) => post<Job<QaReport>>(`${P(pid)}/qa`),
  preview: (pid: string) => post<Job<{ file: string }>>(`${P(pid)}/preview`),

  voice: (pid: string) => get<VoiceView>(`${P(pid)}/voice`),
  setVoiceText: (pid: string, sid: string, text: string) => put<{ ok: boolean }>(`${P(pid)}/voice/${E(sid)}`, { text }),
  redoVoice: (pid: string, scenes: string[]) => post<{ ok: boolean }>(`${P(pid)}/voice/redo`, { scenes }),
  setVoiceEngine: (pid: string, body: { engine: VoiceEngine; voice_id?: string | null; model?: string | null; dialect?: Dialect | null }) =>
    put<{ ok: boolean }>(`${P(pid)}/voice-engine`, body),
  voiceFile: (pid: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return post<{ ok: boolean }>(`${P(pid)}/voice-file`, fd);
  },

  timeline: (pid: string) => get<TimelineView>(`${P(pid)}/timeline`),
  placeVoice: (pid: string, sid: string, at: number | null, gain_db?: number | null) =>
    put<TimelineView>(`${P(pid)}/timeline/voice/${E(sid)}`, { at, gain_db: gain_db ?? null }),
  addAudio: (pid: string, file: File, opts: { at: number; gain_db?: number; fade_in?: number; fade_out?: number; duck?: boolean }) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("at", String(Math.max(0, opts.at)));
    fd.append("gain_db", String(opts.gain_db ?? 0));
    fd.append("fade_in", String(opts.fade_in ?? 0));
    fd.append("fade_out", String(opts.fade_out ?? 0));
    fd.append("duck", String(opts.duck ?? false));
    return post<AudioClipModel>(`${P(pid)}/timeline/audio`, fd);
  },
  patchAudio: (pid: string, cid: string, body: AudioPatch) => patch<TimelineView>(`${P(pid)}/timeline/audio/${E(cid)}`, body),
  deleteAudio: (pid: string, cid: string) => del<TimelineView>(`${P(pid)}/timeline/audio/${E(cid)}`),
  setMusic: (pid: string, body: MusicIn) => put<TimelineView>(`${P(pid)}/timeline/music`, body),

  addFix: (pid: string, body: FixIn) => post<FixResult>(`${P(pid)}/fixes`, body),
  undoFix: (pid: string, sid: string) => del<{ scene: string; removed: Fix | null }>(`${P(pid)}/fixes/${E(sid)}`),

  jobs: (project?: string, limit = 50) =>
    get<Job[]>(`/api/jobs?limit=${limit}${project ? `&project=${E(project)}` : ""}`),
  job: <R = unknown>(jid: string) => get<Job<R>>(`/api/jobs/${E(jid)}`),
  cancelJob: (jid: string) => post<Job>(`/api/jobs/${E(jid)}/cancel`),
  jobEventsUrl: (jid: string, since = 0) => `/api/jobs/${E(jid)}/events${since ? `?since=${since}` : ""}`,
};

// ====================================================================== helpers
/** The web delivery of a project (`*_web.mp4`), else any mp4 that is not an extra export. */
export function mainVideo(media: Media | null | undefined): string | null {
  if (!media) return null;
  const mp4 = media.outputs.filter((o) => o.name.toLowerCase().endsWith(".mp4"));
  return (mp4.find((o) => o.name.endsWith("_web.mp4")) ?? mp4.find((o) => !o.name.startsWith("export_")) ?? mp4[0])?.url ?? null;
}

export const isRunning = (j: Pick<Job, "status">) => j.status === "queued" || j.status === "running";
