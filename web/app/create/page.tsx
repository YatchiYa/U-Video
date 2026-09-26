"use client";

import { ArrowLeft, ArrowRight, Check, Globe, ImagePlus, Loader2, Sparkles, UserRound, Wand2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useId, useRef, useState, type ReactNode } from "react";
import { JobPanel } from "@/components/JobPanel";
import { Button, Card, cx, ErrorBox, Field, inputClass, Notice, Skeleton } from "@/components/ui";
import { ApiError, api, type Aspect, type Job, type Mode, type Quality, type SiteResult } from "@/lib/api";
import { errorText, languageLabel, slugify } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useI18n, type Key } from "@/lib/i18n";
import { LENGTH_PRESETS, MODE_META } from "@/lib/meta";

type Photo = { ref: string; name: string; preview: string };
const MODES: Mode[] = ["ugc", "influencer", "faceless", "promo"];
const ASPECTS: Aspect[] = ["9:16", "16:9", "1:1", "4:5"];
const QUALITIES: Quality[] = ["draft", "standard", "high", "tv"];
const QUALITY_EMOJI: Record<Quality, string> = { draft: "✏️", standard: "👍", high: "💎", tv: "📺" };

// ---------------------------------------------------------------- bits
function ChoiceCard({ selected, onClick, children, className }: { selected: boolean; onClick: () => void; children: ReactNode; className?: string }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onClick}
      className={cx(
        "relative flex rounded-2xl border-2 bg-surface p-4 text-left transition",
        selected ? "border-brand-500 shadow-[var(--shadow-lift)] ring-4 ring-brand-100" : "border-line hover:border-brand-300 hover:bg-brand-50/40",
        className,
      )}
    >
      {selected && (
        <span className="absolute right-3 top-3 grid size-6 place-items-center rounded-full bg-brand-600 text-white">
          <Check className="size-4" aria-hidden />
        </span>
      )}
      {children}
    </button>
  );
}

function AspectShape({ aspect }: { aspect: Aspect }) {
  const size: Record<Aspect, string> = { "9:16": "h-16 w-9", "16:9": "h-9 w-16", "1:1": "size-12", "4:5": "h-14 w-11" };
  return <span className={cx("block rounded-md border-[3px] border-current", size[aspect])} aria-hidden />;
}

function PhotoPicker({ label, hint, photos, setPhotos, max = 6 }: { label: string; hint: string; photos: Photo[]; setPhotos: (f: (p: Photo[]) => Photo[]) => void; max?: number }) {
  const { t } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const id = useId();

  const add = async (files: FileList | null) => {
    if (!files) return;
    setError(null);
    const list = Array.from(files).slice(0, Math.max(0, max - photos.length));
    setBusy((n) => n + list.length);
    await Promise.all(
      list.map(async (f) => {
        try {
          const up = await api.upload(f);
          setPhotos((ps) => [...ps, { ref: up.ref, name: f.name, preview: URL.createObjectURL(f) }]);
        } catch (e) {
          setError(`${f.name}: ${errorText(e, t)}`);
        } finally {
          setBusy((n) => n - 1);
        }
      }),
    );
    if (input.current) input.current.value = "";
  };

  return (
    <div className="flex flex-col gap-3">
      <div>
        <h3 className="font-bold" id={id}>
          {label} <span className="font-normal text-muted">({t("common.optional")})</span>
        </h3>
        <p className="text-sm text-muted">{hint}</p>
      </div>
      <div className="flex flex-wrap gap-3" aria-labelledby={id}>
        {photos.map((p) => (
          <div key={p.ref} className="relative size-24 overflow-hidden rounded-xl border border-line bg-ink/5">
            {/* eslint-disable-next-line @next/next/no-img-element -- local blob preview */}
            <img src={p.preview} alt={p.name} className="size-full object-cover" />
            <button
              type="button"
              onClick={() => setPhotos((ps) => ps.filter((x) => x.ref !== p.ref))}
              className="absolute right-1 top-1 rounded-full bg-ink/70 p-1 text-white hover:bg-ink"
              aria-label={`${t("wiz.photos.remove")}: ${p.name}`}
            >
              <X className="size-3.5" />
            </button>
          </div>
        ))}
        {Array.from({ length: busy }, (_, i) => (
          <div key={`b${i}`} className="grid size-24 place-items-center rounded-xl border border-line bg-ink/5" role="status">
            <Loader2 className="size-5 animate-spin text-brand-500" aria-label={t("wiz.photos.uploading")} />
          </div>
        ))}
        {photos.length + busy < max && (
          <button
            type="button"
            onClick={() => input.current?.click()}
            className="flex size-24 flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed border-brand-300 bg-brand-50/60 text-xs font-semibold text-brand-700 hover:bg-brand-50"
          >
            <ImagePlus className="size-6" aria-hidden />
            {t("wiz.photos.add")}
          </button>
        )}
        <input ref={input} type="file" accept="image/png,image/jpeg,image/webp,image/heic,image/avif" multiple hidden onChange={(e) => add(e.target.files)} />
      </div>
      {error && <ErrorBox error={error} />}
    </div>
  );
}

// ---------------------------------------------------------------- page
export default function CreatePage() {
  const { t, tx, lang } = useI18n();
  const router = useRouter();
  const catalog = useData("catalog", api.catalog);
  const personas = useData("personas", api.personas);

  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<Mode | null>(null);
  const [brief, setBrief] = useState("");
  const [url, setUrl] = useState("");
  const [siteJob, setSiteJob] = useState<Job<SiteResult> | null>(null);
  const [site, setSite] = useState<SiteResult | null>(null);
  const [siteError, setSiteError] = useState<string | null>(null);
  const [faces, setFaces] = useState<Photo[]>([]);
  const [products, setProducts] = useState<Photo[]>([]);
  const [productDesc, setProductDesc] = useState("");
  const [persona, setPersona] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(20);
  const [aspect, setAspect] = useState<Aspect | null>(null);
  const [quality, setQuality] = useState<Quality>("standard");
  const [language, setLanguage] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createJob, setCreateJob] = useState<Job<{ id: string }> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onCamera = mode === "ugc" || mode === "influencer";
  const effAspect: Aspect = aspect ?? (mode === "promo" ? "16:9" : "9:16");
  const effLanguage = language ?? (lang === "fr" ? "French" : "English");
  const urlOk = !url || /^https?:\/\/\S+\.\S+/.test(url.trim());
  const slug = slugify(name);

  const STEPS: Key[] = ["wiz.kind.q", "wiz.brief.q", "wiz.photos.q", "wiz.format.q", "wiz.final.q"];
  const canNext = [!!mode, brief.trim().length >= 3 && urlOk, true, true, !!slug][step];
  const need = [t("wiz.need.kind"), brief.trim().length < 3 ? t("wiz.need.brief") : t("wiz.url.invalid"), "", "", t("wiz.need.name")][step];

  const analyze = async () => {
    setSiteError(null);
    setSite(null);
    try {
      setSiteJob(await api.analyzeSite(url.trim()));
    } catch (e) {
      setSiteError(errorText(e, t));
    }
  };

  const create = async () => {
    if (!mode || !slug) return;
    setCreating(true);
    setError(null);
    try {
      const job = await api.createProject({
        name: slug,
        mode,
        brief: brief.trim(),
        seconds,
        aspect: effAspect,
        quality,
        language: effLanguage,
        url: url.trim() || null,
        persona: onCamera ? persona : null,
        face_uploads: onCamera ? faces.map((f) => f.ref) : [],
        product: productDesc.trim() || null,
        product_uploads: products.map((f) => f.ref),
      });
      setCreateJob(job);
    } catch (e) {
      setError(e instanceof ApiError && e.status === 409 ? `${t("wiz.nameTaken")}\n(${e.message})` : errorText(e, t));
    } finally {
      setCreating(false);
    }
  };

  // ------------------------------------------------------------ creating: progress then redirect
  if (createJob) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        <div className="text-center">
          <div className="mb-3 text-6xl" aria-hidden>
            🎬
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight">{t("wiz.creating")}</h1>
          <p className="mt-2 text-muted">{t("wiz.creating.hint")}</p>
        </div>
        <JobPanel
          jobId={createJob.id}
          initial={createJob}
          expectation={t("wiz.creating.hint")}
          onFinish={(j) => {
            const id = (j.result as { id?: string } | null)?.id ?? j.project;
            if (j.status === "done" && id) router.push(`/projects/${encodeURIComponent(id)}`);
          }}
        />
        <div className="flex justify-center">
          <Button variant="secondary" onClick={() => setCreateJob(null)} icon={<ArrowLeft className="size-4" />}>
            {t("common.back")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      {/* progress */}
      <div>
        <p className="text-sm font-semibold text-brand-700">{t("wiz.step", { n: step + 1, total: STEPS.length })}</p>
        <div className="mt-2 flex gap-1.5" aria-hidden>
          {STEPS.map((_, i) => (
            <div key={i} className={cx("h-2 flex-1 rounded-full transition-colors", i <= step ? "bg-brand-500" : "bg-ink/10")} />
          ))}
        </div>
        <h1 className="mt-5 text-3xl font-extrabold tracking-tight">{t(STEPS[step])}</h1>
      </div>

      {/* ---------------------------------------------------------- step 1: kind */}
      {step === 0 && (
        <>
          <p className="-mt-3 text-muted">{t("wiz.kind.hint")}</p>
          {catalog.error !== undefined && <ErrorBox error={errorText(catalog.error, t)} onRetry={catalog.reload} />}
          <div role="radiogroup" aria-label={t("wiz.kind.q")} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {(catalog.data?.modes.map((m) => m.id) ?? (catalog.loading ? [] : MODES)).map((m) => (
              <ChoiceCard key={m} selected={mode === m} onClick={() => setMode(m)} className="flex-col gap-3 p-5">
                <span className={cx("grid size-16 place-items-center rounded-2xl bg-gradient-to-br text-4xl", MODE_META[m].gradient)} aria-hidden>
                  {MODE_META[m].emoji}
                </span>
                <span className="text-lg font-bold">{tx(`mode.${m}`, m)}</span>
                <span className="text-sm text-muted">{tx(`mode.${m}.desc`, catalog.data?.modes.find((x) => x.id === m)?.description)}</span>
              </ChoiceCard>
            ))}
            {catalog.loading && Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-48" />)}
          </div>
        </>
      )}

      {/* ---------------------------------------------------------- step 2: brief + website */}
      {step === 1 && mode && (
        <Card className="flex flex-col gap-6 p-6">
          <p className="-mt-1 text-muted">{t("wiz.brief.hint")}</p>
          <Field label={t("wiz.brief.label")} htmlFor="brief">
            <textarea
              id="brief"
              dir="auto"
              rows={5}
              value={brief}
              onChange={(e) => setBrief(e.target.value)}
              placeholder={t("wiz.brief.placeholder")}
              className={cx(inputClass, "resize-y text-base")}
            />
          </Field>
          <div>
            <p className="mb-2 text-sm font-medium text-muted">{t("wiz.brief.examples")}</p>
            <div className="flex flex-col gap-2">
              {([1, 2] as const).map((i) => {
                const ex = t(`ex.${mode}.${i}` as Key);
                return (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setBrief(ex)}
                    className="flex items-start gap-2 rounded-xl border border-line bg-canvas/60 px-3 py-2.5 text-left text-sm hover:border-brand-300 hover:bg-brand-50"
                  >
                    <Sparkles className="mt-0.5 size-4 shrink-0 text-brand-500" aria-hidden />
                    {ex}
                  </button>
                );
              })}
            </div>
          </div>
          <div className={cx("flex flex-col gap-3 rounded-2xl p-4", mode === "promo" ? "bg-brand-50" : "bg-canvas")}>
            <Field label={t("wiz.url.label")} htmlFor="url" hint={t("wiz.url.hint")} optional={mode !== "promo"}>
              <div className="flex flex-col gap-2 sm:flex-row">
                <div className="relative flex-1">
                  <Globe className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
                  <input
                    id="url"
                    type="url"
                    inputMode="url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://"
                    className={cx(inputClass, "pl-9")}
                    aria-invalid={!urlOk}
                  />
                </div>
                <Button variant="soft" onClick={analyze} disabled={!url.trim() || !urlOk} icon={<Wand2 className="size-4" />}>
                  {t("wiz.url.analyze")}
                </Button>
              </div>
            </Field>
            {!urlOk && <p className="text-sm text-red-700">{t("wiz.url.invalid")}</p>}
            {siteError && <ErrorBox error={siteError} />}
            {siteJob && !site && (
              <JobPanel<SiteResult>
                key={siteJob.id}
                jobId={siteJob.id}
                initial={siteJob}
                expectation="≈ 1 min."
                onFinish={(j) => j.status === "done" && j.result && setSite(j.result)}
                onDismiss={() => setSiteJob(null)}
              />
            )}
            {site && (
              <div className="rounded-2xl border border-emerald-200 bg-surface p-4">
                <p className="mb-3 flex items-center gap-2 font-bold text-emerald-800">
                  <Check className="size-5" aria-hidden /> {t("wiz.url.found")}
                </p>
                <dl className="grid gap-3 text-sm sm:grid-cols-[auto_1fr]">
                  <dt className="font-semibold text-muted">{t("wiz.url.brand")}</dt>
                  <dd dir="auto" className="font-bold">
                    {site.brand.name || site.title || "—"}
                    {site.brand.tagline && <span className="ml-2 font-normal text-muted">{site.brand.tagline}</span>}
                  </dd>
                  <dt className="font-semibold text-muted">{t("wiz.url.colors")}</dt>
                  <dd className="flex flex-wrap gap-2">
                    {(["primary", "secondary", "accent", "dark", "light"] as const).map((k) => (
                      <span key={k} className="inline-flex items-center gap-1.5 rounded-full border border-line px-2 py-0.5 font-mono text-xs">
                        <span className="size-4 rounded-full border border-ink/10" style={{ background: site.brand[k] }} aria-hidden />
                        {site.brand[k]}
                      </span>
                    ))}
                  </dd>
                  {site.sections.length > 0 && (
                    <>
                      <dt className="font-semibold text-muted">{t("wiz.url.sections")}</dt>
                      <dd>
                        <ul className="flex flex-wrap gap-1.5">
                          {site.sections.map((s, i) => (
                            <li key={i} dir="auto" className="rounded-full bg-ink/5 px-2.5 py-0.5 text-xs">
                              {s}
                            </li>
                          ))}
                        </ul>
                      </dd>
                    </>
                  )}
                </dl>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* ---------------------------------------------------------- step 3: photos + persona */}
      {step === 2 && (
        <Card className="flex flex-col gap-8 p-6">
          <p className="-mt-1 text-muted">{t("wiz.photos.hint")}</p>
          {onCamera && <PhotoPicker label={t("wiz.photos.face")} hint={t("wiz.photos.face.hint")} photos={faces} setPhotos={setFaces} max={3} />}
          <div className="flex flex-col gap-4">
            <PhotoPicker label={t("wiz.photos.product")} hint={t("wiz.photos.product.hint")} photos={products} setPhotos={setProducts} />
            <Field label={t("wiz.photos.productDesc")} htmlFor="pdesc" optional>
              <input
                id="pdesc"
                dir="auto"
                value={productDesc}
                onChange={(e) => setProductDesc(e.target.value)}
                placeholder={t("wiz.photos.productDesc.placeholder")}
                className={inputClass}
              />
            </Field>
          </div>
          {onCamera && (
            <div className="flex flex-col gap-3">
              <h3 className="font-bold">{t("wiz.persona.q")}</h3>
              <div role="radiogroup" aria-label={t("wiz.persona.q")} className="grid gap-3 sm:grid-cols-2">
                <ChoiceCard selected={persona === null} onClick={() => setPersona(null)} className="items-start gap-3">
                  <span className="grid size-12 shrink-0 place-items-center rounded-full bg-gradient-to-br from-brand-200 to-coral-100 text-2xl" aria-hidden>
                    ✨
                  </span>
                  <span className="pr-6">
                    <span className="block font-bold">{t("wiz.persona.none")}</span>
                    <span className="block text-sm text-muted">{t("wiz.persona.none.desc")}</span>
                  </span>
                </ChoiceCard>
                {personas.loading && <Skeleton className="h-24" />}
                {personas.data?.map((p) => (
                  <ChoiceCard key={p.name} selected={persona === p.name} onClick={() => setPersona(p.name)} className="items-start gap-3">
                    {p.image_urls?.[0] ? (
                      // eslint-disable-next-line @next/next/no-img-element -- served by the API, no optimization needed
                      <img src={p.image_urls[0]} alt="" className="size-12 shrink-0 rounded-full object-cover" />
                    ) : (
                      <span className="grid size-12 shrink-0 place-items-center rounded-full bg-brand-100 text-lg font-bold capitalize text-brand-700" aria-hidden>
                        {p.name.slice(0, 1) || <UserRound className="size-5" />}
                      </span>
                    )}
                    <span className="min-w-0 pr-6">
                      <span className="block font-bold capitalize" dir="auto">
                        {p.name} <span className="text-xs font-normal text-muted">· {p.language}</span>
                      </span>
                      <span className="line-clamp-3 block text-sm text-muted" dir="auto">
                        {p.description}
                      </span>
                    </span>
                  </ChoiceCard>
                ))}
              </div>
            </div>
          )}
        </Card>
      )}

      {/* ---------------------------------------------------------- step 4: length, format, quality, language */}
      {step === 3 && (
        <Card className="flex flex-col gap-8 p-6">
          <div className="flex flex-col gap-3">
            <div className="flex items-baseline justify-between">
              <label htmlFor="len" className="font-bold">
                {t("wiz.length")}
              </label>
              <span className="text-2xl font-extrabold tabular-nums text-brand-700">{t("wiz.length.value", { n: seconds })}</span>
            </div>
            <input id="len" type="range" min={5} max={120} step={1} value={seconds} onChange={(e) => setSeconds(Number(e.target.value))} className="w-full" />
            <div className="flex flex-wrap gap-2">
              {LENGTH_PRESETS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSeconds(s)}
                  aria-pressed={seconds === s}
                  className={cx(
                    "h-10 min-w-14 rounded-xl border px-3 text-sm font-semibold tabular-nums",
                    seconds === s ? "border-brand-500 bg-brand-600 text-white" : "border-line bg-surface hover:border-brand-300",
                  )}
                >
                  {s} s
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-3">
            <h3 className="font-bold">{t("wiz.format")}</h3>
            <div role="radiogroup" aria-label={t("wiz.format")} className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {ASPECTS.map((a) => (
                <ChoiceCard key={a} selected={effAspect === a} onClick={() => setAspect(a)} className="flex-col items-center gap-2 text-center">
                  <span className="grid h-20 place-items-center text-brand-600">
                    <AspectShape aspect={a} />
                  </span>
                  <span className="font-bold">
                    {tx(`aspect.${a}`, a)} <span className="font-normal text-muted">{a}</span>
                  </span>
                  <span className="text-xs text-muted">{tx(`aspect.${a}.desc`)}</span>
                </ChoiceCard>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-3">
            <h3 className="font-bold">{t("wiz.quality")}</h3>
            <div role="radiogroup" aria-label={t("wiz.quality")} className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {QUALITIES.map((q) => (
                <ChoiceCard key={q} selected={quality === q} onClick={() => setQuality(q)} className="flex-col gap-1">
                  <span className="text-2xl" aria-hidden>
                    {QUALITY_EMOJI[q]}
                  </span>
                  <span className="font-bold">{tx(`quality.${q}`, q)}</span>
                  <span className="text-xs text-muted">{tx(`quality.${q}.desc`)}</span>
                </ChoiceCard>
              ))}
            </div>
          </div>

          <Field label={t("wiz.language")} htmlFor="lang" hint={t("wiz.language.hint")}>
            <select id="lang" value={effLanguage} onChange={(e) => setLanguage(e.target.value)} className={cx(inputClass, "max-w-xs")}>
              {(catalog.data?.languages ?? [effLanguage]).map((l) => (
                <option key={l} value={l}>
                  {languageLabel(l, lang)}
                </option>
              ))}
            </select>
          </Field>
        </Card>
      )}

      {/* ---------------------------------------------------------- step 5: name + summary */}
      {step === 4 && mode && (
        <Card className="flex flex-col gap-6 p-6">
          <Field label={t("wiz.name")} htmlFor="name" hint={slug ? t("wiz.name.hint", { slug }) : undefined}>
            <input
              id="name"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setError(null);
              }}
              maxLength={60}
              placeholder="ma_premiere_video"
              className={cx(inputClass, "text-lg")}
            />
          </Field>
          <div>
            <h3 className="mb-3 font-bold">{t("wiz.summary")}</h3>
            <dl className="grid grid-cols-1 gap-x-6 gap-y-2 rounded-2xl bg-canvas p-4 text-sm sm:grid-cols-[auto_1fr]">
              <dt className="text-muted">{t("wiz.sum.kind")}</dt>
              <dd className="font-semibold">
                {MODE_META[mode].emoji} {tx(`mode.${mode}`, mode)}
              </dd>
              <dt className="text-muted">{t("wiz.brief.label")}</dt>
              <dd dir="auto" className="line-clamp-3">
                {brief}
              </dd>
              <dt className="text-muted">{t("wiz.sum.length")}</dt>
              <dd className="font-semibold">{t("wiz.length.value", { n: seconds })}</dd>
              <dt className="text-muted">{t("wiz.sum.format")}</dt>
              <dd className="font-semibold">
                {tx(`aspect.${effAspect}`)} ({effAspect})
              </dd>
              <dt className="text-muted">{t("wiz.sum.quality")}</dt>
              <dd className="font-semibold">{tx(`quality.${quality}`)}</dd>
              <dt className="text-muted">{t("wiz.sum.language")}</dt>
              <dd className="font-semibold">{languageLabel(effLanguage, lang)}</dd>
              {url && (
                <>
                  <dt className="text-muted">{t("wiz.sum.website")}</dt>
                  <dd className="truncate">{url}</dd>
                </>
              )}
              {faces.length + products.length > 0 && (
                <>
                  <dt className="text-muted">{t("wiz.sum.photos")}</dt>
                  <dd>{faces.length + products.length}</dd>
                </>
              )}
              {onCamera && (
                <>
                  <dt className="text-muted">{t("wiz.sum.persona")}</dt>
                  <dd className="capitalize">{persona ?? t("wiz.persona.none")}</dd>
                </>
              )}
            </dl>
          </div>
          {error && <ErrorBox error={error} />}
          <Notice tone="brand" icon={<Sparkles className="size-5 text-brand-600" />}>
            {t("wiz.creating.hint")}
          </Notice>
        </Card>
      )}

      {/* ---------------------------------------------------------- navigation */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-3">
          <Button
            variant="secondary"
            size="lg"
            onClick={() => (step === 0 ? router.push("/") : setStep(step - 1))}
            icon={<ArrowLeft className="size-5" />}
          >
            {t("common.back")}
          </Button>
          {step < STEPS.length - 1 ? (
            <Button size="lg" onClick={() => setStep(step + 1)} disabled={!canNext}>
              {t("common.next")} <ArrowRight className="size-5" aria-hidden />
            </Button>
          ) : (
            <Button size="xl" onClick={create} loading={creating} disabled={!canNext} icon={<Sparkles className="size-6" />}>
              {t("wiz.create")}
            </Button>
          )}
        </div>
        {!canNext && need && <p className="text-right text-sm text-muted">{need}</p>}
      </div>
    </div>
  );
}
