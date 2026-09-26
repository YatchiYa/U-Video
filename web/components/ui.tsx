"use client";

import { AlertTriangle, Loader2, RotateCw, X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import { useI18n } from "@/lib/i18n";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------- button
type Variant = "primary" | "secondary" | "ghost" | "danger" | "coral" | "soft";
type Size = "sm" | "md" | "lg" | "xl";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 shadow-sm shadow-brand-900/10",
  secondary: "bg-surface text-ink border border-line hover:border-brand-300 hover:bg-brand-50",
  ghost: "text-ink hover:bg-ink/5",
  soft: "bg-brand-50 text-brand-700 hover:bg-brand-100",
  danger: "bg-surface text-red-700 border border-red-200 hover:bg-red-50",
  coral: "bg-coral-500 text-white hover:bg-coral-600 shadow-sm shadow-coral-700/20",
};
const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-sm gap-1.5 rounded-lg",
  md: "h-10 px-4 text-sm gap-2 rounded-xl",
  lg: "h-12 px-5 text-base gap-2 rounded-xl",
  xl: "h-16 px-8 text-lg gap-3 rounded-2xl",
};

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  icon,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; loading?: boolean; icon?: ReactNode }) {
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        "inline-flex select-none items-center justify-center font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
    >
      {loading ? <Loader2 className="size-[1.1em] animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("animate-spin text-brand-500", className ?? "size-5")} aria-hidden />;
}

// ---------------------------------------------------------------- surfaces
export function Card({ className, children, ...rest }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...rest} className={cx("rounded-2xl border border-line bg-surface shadow-[var(--shadow-soft)]", className)}>
      {children}
    </div>
  );
}

type Tone = "neutral" | "brand" | "green" | "amber" | "red" | "blue";
const TONES: Record<Tone, string> = {
  neutral: "bg-ink/5 text-ink/70",
  brand: "bg-brand-100 text-brand-800",
  green: "bg-emerald-100 text-emerald-800",
  amber: "bg-amber-100 text-amber-800",
  red: "bg-red-100 text-red-800",
  blue: "bg-sky-100 text-sky-800",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold", TONES[tone], className)}>
      {children}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton rounded-xl", className)} aria-hidden />;
}

export function SkeletonCards({ n = 3, className }: { n?: number; className?: string }) {
  const { t } = useI18n();
  return (
    <div className={className} role="status" aria-live="polite">
      <span className="sr-only">{t("common.loading")}</span>
      {Array.from({ length: n }, (_, i) => (
        <Skeleton key={i} className="h-40" />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- messages
export function ErrorBox({ error, onRetry, className }: { error: string; onRetry?: () => void; className?: string }) {
  const { t } = useI18n();
  return (
    <div role="alert" className={cx("flex gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-red-900", className)}>
      <AlertTriangle className="mt-0.5 size-5 shrink-0 text-red-600" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{t("common.errorTitle")}</p>
        <p className="mt-1 whitespace-pre-wrap break-words text-sm" dir="auto">
          {error}
        </p>
        {onRetry && (
          <Button variant="danger" size="sm" className="mt-3" onClick={onRetry} icon={<RotateCw className="size-4" />}>
            {t("common.retry")}
          </Button>
        )}
      </div>
    </div>
  );
}

export function Notice({ tone = "amber", icon, children, className }: { tone?: "amber" | "blue" | "green" | "brand"; icon?: ReactNode; children: ReactNode; className?: string }) {
  const tones = {
    amber: "border-amber-200 bg-amber-50 text-amber-950",
    blue: "border-sky-200 bg-sky-50 text-sky-950",
    green: "border-emerald-200 bg-emerald-50 text-emerald-950",
    brand: "border-brand-200 bg-brand-50 text-brand-900",
  };
  return (
    <div className={cx("flex items-start gap-3 rounded-2xl border p-4 text-sm", tones[tone], className)}>
      {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

export function EmptyState({ emoji, title, text, action }: { emoji: string; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-3xl border-2 border-dashed border-line bg-surface/60 px-6 py-14 text-center">
      <div className="mb-4 text-5xl" aria-hidden>
        {emoji}
      </div>
      <h2 className="text-xl font-bold">{title}</h2>
      {text && <p className="mt-2 max-w-md text-muted">{text}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- form
export function Field({ label, hint, children, htmlFor, optional }: { label: string; hint?: string; children: ReactNode; htmlFor?: string; optional?: boolean }) {
  const { t } = useI18n();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-sm font-semibold text-ink">
        {label}
        {optional && <span className="ml-1.5 font-normal text-muted">({t("common.optional")})</span>}
      </label>
      {children}
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}

export const inputClass =
  "w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[15px] text-ink placeholder:text-muted/70 outline-none transition focus:border-brand-400 focus:ring-4 focus:ring-brand-100 disabled:bg-ink/5";

export function NumberInput({ value, onChange, step = 0.1, min, max, id, className, ...rest }: {
  value: number | null;
  onChange: (v: number | null) => void;
  step?: number;
  min?: number;
  max?: number;
  id?: string;
  className?: string;
  "aria-label"?: string;
}) {
  return (
    <input
      id={id}
      type="number"
      inputMode="decimal"
      step={step}
      min={min}
      max={max}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      className={cx(inputClass, "tabular-nums", className)}
      {...rest}
    />
  );
}

// ---------------------------------------------------------------- modal (native <dialog>: focus trap + Esc)
export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const { t } = useI18n();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      className={cx(
        "m-auto w-[calc(100%-2rem)] rounded-3xl border border-line bg-surface p-0 text-ink shadow-[var(--shadow-lift)]",
        wide ? "max-w-2xl" : "max-w-lg",
      )}
    >
      {open && (
        <div className="p-6">
          <div className="mb-4 flex items-start justify-between gap-4">
            <h2 id={titleId} className="text-xl font-bold">
              {title}
            </h2>
            <button onClick={onClose} className="rounded-lg p-1.5 text-muted hover:bg-ink/5" aria-label={t("common.close")}>
              <X className="size-5" />
            </button>
          </div>
          {children}
        </div>
      )}
    </dialog>
  );
}

// ---------------------------------------------------------------- toasts
type ToastItem = { id: number; text: string; tone: "ok" | "error" };
const ToastCtx = createContext<(text: string, tone?: "ok" | "error") => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((text: string, tone: "ok" | "error" = "ok") => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, text, tone }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), tone === "error" ? 8000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4" aria-live="polite">
        {items.map((x) => (
          <div
            key={x.id}
            role={x.tone === "error" ? "alert" : "status"}
            className={cx(
              "pointer-events-auto max-w-lg rounded-2xl px-4 py-3 text-sm font-medium shadow-[var(--shadow-lift)]",
              x.tone === "error" ? "bg-red-600 text-white" : "bg-ink text-white",
            )}
            dir="auto"
          >
            {x.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

// ---------------------------------------------------------------- section header
export function SectionTitle({ title, hint, right }: { title: string; hint?: string; right?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="text-xl font-bold tracking-tight">{title}</h2>
        {hint && <p className="mt-1 max-w-2xl text-sm text-muted">{hint}</p>}
      </div>
      {right}
    </div>
  );
}
