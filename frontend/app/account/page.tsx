"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { AuthErrorAlert } from "@/components/auth/AuthCard";
import { EmailForm } from "@/components/auth/EmailForm";
import { GitHubMark, GoogleMark, ProviderButton } from "@/components/auth/ProviderButtons";
import { MailIcon } from "@/components/icons";
import { Alert, Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { authApi } from "@/lib/auth";
import type { AccountProviders, LinkedAccount, Me } from "@/lib/schemas";

const NAME = { google: "Google", github: "GitHub", email: "Email link" } as const;
const MARK = { google: GoogleMark, github: GitHubMark, email: MailIcon } as const;

export default function AccountPage() {
  return (
    <Suspense fallback={null}>
      <Account />
    </Suspense>
  );
}

function Account() {
  const params = useSearchParams();
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [providers, setProviders] = useState<AccountProviders | null>(null);
  const [error, setError] = useState<unknown>(params.get("error"));

  const reload = useCallback(() => authApi.accountProviders().then(setProviders).catch(setError), []);
  useEffect(() => {
    api.me().then((m) => { setMe(m); if (m) void reload(); }).catch((e) => { setError(e); setMe(null); });
  }, [reload]);

  if (me === undefined) return null;
  if (me === null) {
    return (
      <div className="mx-auto max-w-md">
        <Alert tone="info" title="Please sign in">
          <Link href="/signin?next=/account" className="font-medium text-accent underline">Sign in</Link> to see your account.
        </Alert>
      </div>
    );
  }
  const linked = params.get("linked") as keyof typeof NAME | null;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Your account</h1>
        <p className="mt-1 text-muted">Signed in as <strong className="text-fg">{me.email}</strong></p>
      </div>
      {linked && linked in NAME && (
        <Alert tone="ok" title={`${NAME[linked]} connected`} role="status">You can now sign in with it.</Alert>
      )}
      <AuthErrorAlert error={error} />
      <Card>
        <h2 className="text-lg font-semibold">Billing</h2>
        <p className="mt-1 text-sm text-muted">Credits, passes, purchases and receipts.</p>
        <div className="mt-3 flex flex-wrap gap-4">
          <Link href="/account/billing" className="text-sm font-medium text-accent underline">Go to billing</Link>
          {me.role === "admin" && (
            <Link href="/admin/billing" className="text-sm font-medium text-accent underline">Billing admin</Link>
          )}
        </div>
      </Card>
      {providers && <SignInMethods providers={providers} onChange={reload} onError={setError} />}
      <SignOut />
      <DeleteAccount />
    </div>
  );
}

function SignInMethods({ providers, onChange, onError }: {
  providers: AccountProviders;
  onChange: () => void;
  onError: (e: unknown) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const has = (p: LinkedAccount["provider"]) => providers.accounts.some((a) => a.provider === p);

  async function remove(account: LinkedAccount) {
    setBusy(account.id);
    onError(null);
    try {
      await authApi.unlink(account.id);
      onChange();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <h2 className="text-lg font-semibold">Ways to sign in</h2>
      <ul className="mt-4 divide-y divide-border" aria-label="Connected sign-in methods">
        {providers.accounts.map((a) => {
          const Mark = MARK[a.provider];
          return (
            <li key={a.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <div className="flex items-center gap-3">
                <Mark />
                <div>
                  <p className="text-sm font-medium">{NAME[a.provider]}</p>
                  <p className="text-xs text-muted">{a.email}</p>
                </div>
              </div>
              <Button variant="secondary" className="min-h-9 px-3" busy={busy === a.id}
                disabled={!providers.can_unlink} onClick={() => void remove(a)}
                aria-label={`Disconnect ${NAME[a.provider]} (${a.email})`}>
                Disconnect
              </Button>
            </li>
          );
        })}
      </ul>
      {!providers.can_unlink && (
        <p className="mt-2 text-xs text-muted">
          This is your only way to sign in, so it can&apos;t be removed. Connect another one first.
        </p>
      )}

      <h3 className="mt-6 text-sm font-medium">Add a way to sign in</h3>
      <div className="mt-3 space-y-3">
        {!has("google") && <ProviderButton provider="google" available={providers.available.google} link />}
        {!has("github") && <ProviderButton provider="github" available={providers.available.github} link />}
        <EmailForm id="link-email" label="Email address for sign-in links" button="Send confirmation link"
          sentTitle="Check your email" send={authApi.linkEmail} />
      </div>
    </Card>
  );
}

function SignOut() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  return (
    <Button variant="secondary" busy={busy} onClick={async () => {
      setBusy(true);
      try { await api.logout(); } finally { router.replace("/signin"); }
    }}>
      Sign out
    </Button>
  );
}

function DeleteAccount() {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <Card>
      <h2 className="text-lg font-semibold">Delete account</h2>
      <p className="mt-1 text-sm text-muted">
        This removes your account and every connected sign-in method. You&apos;d need a new invite to come back.
      </p>
      <div className="mt-4 space-y-3">
        <AuthErrorAlert error={error} />
        {confirming ? (
          <div role="group" aria-label="Confirm account deletion" className="flex flex-wrap items-center gap-2">
            <span className="text-sm">Delete your account for good?</span>
            <Button variant="danger" busy={busy} onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await authApi.deleteAccount();
                router.replace("/");
              } catch (e) {
                setError(e);
                setBusy(false);
              }
            }}>
              Yes, delete my account
            </Button>
            <Button variant="ghost" onClick={() => setConfirming(false)} autoFocus>Cancel</Button>
          </div>
        ) : (
          <Button variant="danger" onClick={() => setConfirming(true)}>Delete account…</Button>
        )}
      </div>
    </Card>
  );
}
