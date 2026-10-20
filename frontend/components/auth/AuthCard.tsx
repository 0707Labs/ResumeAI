"use client";

import type { ReactNode } from "react";

import { Alert, Card } from "@/components/ui";
import { authMessage } from "@/lib/auth";

/** The narrow centred card every sign-in step uses. */
export function AuthCard({ title, intro, children }: { title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <div className="mx-auto max-w-md">
      <Card>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {intro && <div className="mt-2 text-sm text-muted">{intro}</div>}
        <div className="mt-6 space-y-5">{children}</div>
      </Card>
    </div>
  );
}

/** An auth error code (or AuthError) as a friendly alert with icon and words. */
export function AuthErrorAlert({ error, children }: { error: unknown; children?: ReactNode }) {
  if (!error) return null;
  const { title, body } = authMessage(error);
  return (
    <Alert tone="bad" title={title} role="alert">
      {body}
      {children && <div className="mt-2">{children}</div>}
    </Alert>
  );
}
