"use client";

import type { ReactNode } from "react";

import { AlertIcon, CheckIcon, ErrorIcon, InfoIcon } from "./icons";

export function Spinner({ label }: { label?: string }) {
  return (
    <span
      role={label ? "status" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent"
    />
  );
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-accent-fg hover:bg-accent-hover disabled:opacity-50",
  secondary: "border border-border-strong bg-surface text-fg hover:bg-surface-2 disabled:opacity-50",
  ghost: "text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-50",
  danger: "border border-bad/40 bg-surface text-bad hover:bg-bad-bg disabled:opacity-50",
};

export function Button({
  variant = "primary",
  busy,
  children,
  className = "",
  type = "button",
  ...props
}: { variant?: Variant; busy?: boolean } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type={type}
      {...props}
      disabled={props.disabled || busy}
      aria-busy={busy || undefined}
      className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
    >
      {busy && <Spinner />}
      {children}
    </button>
  );
}

export function Card({ children, className = "", as: Tag = "section", ...rest }: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "form";
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <Tag {...rest} className={`rounded-2xl border border-border bg-surface p-5 sm:p-6 ${className}`}>
      {children}
    </Tag>
  );
}

type Tone = "info" | "ok" | "warn" | "bad";
const ALERT: Record<Tone, { cls: string; Icon: typeof InfoIcon; word: string }> = {
  info: { cls: "border-border bg-surface-2 text-fg", Icon: InfoIcon, word: "Note" },
  ok: { cls: "border-ok/30 bg-ok-bg text-ok", Icon: CheckIcon, word: "Done" },
  warn: { cls: "border-warn/30 bg-warn-bg text-warn", Icon: AlertIcon, word: "Heads up" },
  bad: { cls: "border-bad/30 bg-bad-bg text-bad", Icon: ErrorIcon, word: "Problem" },
};

/** A message box with an icon and a visible label word, so tone isn't color-only. */
export function Alert({ tone = "info", title, children, role }: {
  tone?: Tone;
  title?: string;
  children?: ReactNode;
  role?: "alert" | "status";
}) {
  const { cls, Icon, word } = ALERT[tone];
  return (
    <div role={role} className={`flex gap-3 rounded-xl border px-4 py-3 text-sm ${cls}`}>
      <Icon className="mt-0.5 h-4 w-4" />
      <div className="min-w-0">
        <p className="font-medium">{title ?? word}</p>
        {children && <div className="mt-0.5 text-fg/90">{children}</div>}
      </div>
    </div>
  );
}

export function Label({ htmlFor, children, hint }: { htmlFor: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="block text-sm font-medium text-fg">
      {children}
      {hint && <span className="ml-1 font-normal text-muted">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "mt-1.5 block w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm text-fg placeholder:text-muted/70 focus-visible:border-accent";
/** The same look for a control that sits in a row (filters, pickers): no top margin, own width. */
export const inlineInputClass =
  "block rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm text-fg placeholder:text-muted/70 focus-visible:border-accent";
