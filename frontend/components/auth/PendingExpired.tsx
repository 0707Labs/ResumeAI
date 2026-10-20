import Link from "next/link";

import { AuthCard, AuthErrorAlert } from "./AuthCard";

export function PendingExpired({ error }: { error?: unknown }) {
  return (
    <AuthCard title="Let's start again">
      <AuthErrorAlert error={error || "pending_expired"} />
      <Link href="/signup" className="text-sm font-medium text-accent underline">Back to sign up</Link>
    </AuthCard>
  );
}
