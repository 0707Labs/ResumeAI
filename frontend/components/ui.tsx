"use client";

import type { ReactNode } from "react";

export function Card({ title, actions, children, className = "" }: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white p-5 shadow-sm ${className}`}>
      {(title || actions) && (
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
          {title && <h2 className="text-base font-semibold text-slate-900">{title}</h2>}
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

type Variant = "primary" | "secondary" | "ghost" | "success" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-slate-900 text-white hover:bg-slate-700 disabled:bg-slate-300",
  secondary: "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50 disabled:text-slate-400",
  ghost: "text-slate-600 hover:bg-slate-100 disabled:text-slate-300",
  success: "bg-emerald-600 text-white hover:bg-emerald-500 disabled:bg-emerald-200",
  danger: "border border-rose-300 bg-white text-rose-700 hover:bg-rose-50 disabled:text-rose-300",
};

export function Button({ variant = "primary", busy, children, className = "", ...props }: {
  variant?: Variant;
  busy?: boolean;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      disabled={props.disabled || busy}
      className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
    >
      {busy && <Spinner />}
      {children}
    </button>
  );
}

export function Spinner() {
  return (
    <span
      aria-hidden
      className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent"
    />
  );
}

type Tone = "slate" | "green" | "amber" | "rose" | "blue" | "violet";
const TONES: Record<Tone, string> = {
  slate: "bg-slate-100 text-slate-700 ring-slate-200",
  green: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  rose: "bg-rose-50 text-rose-800 ring-rose-200",
  blue: "bg-sky-50 text-sky-800 ring-sky-200",
  violet: "bg-violet-50 text-violet-800 ring-violet-200",
};

export function Pill({ tone = "slate", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function ErrorBanner({ error, onDismiss }: { error: string | null; onDismiss?: () => void }) {
  if (!error) return null;
  return (
    <div role="alert" className="mb-4 flex items-start justify-between gap-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
      <span>{error}</span>
      {onDismiss && (
        <button onClick={onDismiss} className="text-rose-600 hover:text-rose-900" aria-label="Dismiss">
          ×
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">{children}</p>;
}

export function Note({ children }: { children: ReactNode }) {
  return <p className="text-xs leading-relaxed text-slate-500">{children}</p>;
}
