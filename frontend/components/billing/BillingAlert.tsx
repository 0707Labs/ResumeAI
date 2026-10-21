"use client";

import { Alert } from "@/components/ui";
import { billingMessage } from "@/lib/billing";

/** A billing error code (or AuthError) as a friendly alert. */
export function BillingAlert({ error }: { error: unknown }) {
  if (!error) return null;
  const { title, body } = billingMessage(error);
  return <Alert tone="bad" title={title} role="alert">{body}</Alert>;
}
