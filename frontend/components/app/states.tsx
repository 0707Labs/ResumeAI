/** Shared building blocks for signed-in pages: a header, and the empty, loading and error states. */
import type { ReactNode } from "react";

import { ErrorIcon } from "@/components/icons";
import { Button } from "@/components/ui";

export function PageHeader({ title, intro, actions }: { title: string; intro?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold text-fg">{title}</h1>
        {intro && <p className="mt-1 max-w-2xl text-sm text-muted">{intro}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-border-strong px-6 py-8 text-center">
      <p className="font-medium text-fg">{title}</p>
      {children && <div className="mx-auto mt-1 max-w-md text-sm text-muted">{children}</div>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-bad/30 bg-bad-bg px-4 py-3">
      <p className="flex items-center gap-2 text-sm text-bad"><ErrorIcon />{message}</p>
      {onRetry && <Button variant="secondary" className="min-h-9 px-3" onClick={onRetry}>Try again</Button>}
    </div>
  );
}

/** A grey placeholder block while content loads. Hidden from screen readers; pair a
 * Skeleton group with one visually hidden "Loading" status. */
export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div aria-hidden="true" className={`animate-pulse rounded-md bg-surface-2 motion-reduce:animate-none ${className}`} />;
}

export function LoadingStatus({ label = "Loading" }: { label?: string }) {
  return <p role="status" className="sr-only">{label}</p>;
}
