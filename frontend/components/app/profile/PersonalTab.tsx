"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { Avatar } from "@/components/app/Avatar";
import { ErrorState, LoadingStatus, Skeleton } from "@/components/app/states";
import { AuthErrorAlert } from "@/components/auth/AuthCard";
import { EmailForm } from "@/components/auth/EmailForm";
import { GitHubMark, GoogleMark, ProviderButton } from "@/components/auth/ProviderButtons";
import { CheckIcon, MailIcon } from "@/components/icons";
import { Alert, Button, Card, Label, inputClass } from "@/components/ui";
import { AuthError, authApi } from "@/lib/auth";
import type { AccountProviders, LinkedAccount, Profile } from "@/lib/schemas";
import { userApi, userError } from "@/lib/user";

const NAME = { google: "Google", github: "GitHub", email: "Email link" } as const;
const MARK = { google: GoogleMark, github: GitHubMark, email: MailIcon } as const;
const AVATAR_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
const AVATAR_MAX = 2 * 1024 * 1024;

export function PersonalTab({ linked, error: initialError }: { linked: string | null; error: string | null }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const load = useCallback(() => {
    setLoadError(null);
    userApi.profile().then(setProfile).catch((e) => setLoadError(userError(e)));
  }, []);
  useEffect(load, [load]);

  if (loadError) return <ErrorState message={loadError} onRetry={load} />;
  if (!profile) {
    return <Card className="space-y-4"><LoadingStatus label="Loading your profile" /><Skeleton className="h-20 w-20 rounded-full" /><Skeleton className="h-10" /><Skeleton className="h-10" /></Card>;
  }
  return (
    <div className="space-y-6">
      {linked && linked in NAME && (
        <Alert tone="ok" title={`${NAME[linked as keyof typeof NAME]} connected`} role="status">You can now sign in with it.</Alert>
      )}
      <PictureCard profile={profile} onChange={setProfile} />
      <DetailsCard profile={profile} onChange={setProfile} />
      <SignInMethods initialError={initialError} />
    </div>
  );
}

function PictureCard({ profile, onChange }: { profile: Profile; onChange: (p: Profile) => void }) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<Profile>) {
    setBusy(true);
    setError(null);
    try {
      onChange(await fn());
      router.refresh();  // the header's avatar comes from the server-rendered layout
    } catch (e) {
      setError(userError(e));
    } finally {
      setBusy(false);
    }
  }
  function pick(file: File | undefined) {
    if (!file) return;
    if (!AVATAR_TYPES.includes(file.type)) return setError(userError(new AuthError("avatar_unsupported_type", 415)));
    if (file.size > AVATAR_MAX) return setError("That picture is over 2 MB. Try a smaller one.");
    void run(() => userApi.uploadAvatar(file));
  }

  return (
    <Card>
      <h2 className="font-medium text-fg">Picture</h2>
      <div className="mt-4 flex flex-wrap items-center gap-4">
        <Avatar src={profile.avatar_url} name={profile.name} email={profile.email} size="lg" />
        <div className="space-y-2">
          <p className="text-sm text-muted">
            {profile.avatar_source === "provider" ? "From your Google or GitHub account."
              : profile.avatar_source === "upload" ? "Your uploaded picture." : "Your initials, for now."}
            {" "}PNG, JPEG, WebP or GIF up to 2 MB; we keep a small square copy.
          </p>
          <div className="flex flex-wrap gap-2">
            <input ref={input} type="file" accept={AVATAR_TYPES.join(",")} className="sr-only" tabIndex={-1}
              aria-hidden="true" onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
            <Button variant="secondary" busy={busy} onClick={() => input.current?.click()}>
              {profile.avatar_url ? "Change picture" : "Upload a picture"}
            </Button>
            {profile.avatar_url && (
              <Button variant="ghost" disabled={busy} onClick={() => run(() => userApi.removeAvatar())}>
                Use initials instead
              </Button>
            )}
          </div>
        </div>
      </div>
      {error && <p role="alert" className="mt-3 text-sm text-bad">{error}</p>}
    </Card>
  );
}

function DetailsCard({ profile, onChange }: { profile: Profile; onChange: (p: Profile) => void }) {
  const id = useId();
  const [name, setName] = useState(profile.name ?? "");
  const [phone, setPhone] = useState(profile.phone ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const dirty = name.trim() !== (profile.name ?? "") || phone.trim() !== (profile.phone ?? "");

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const body: { name?: string; phone?: string | null } = { phone: phone.trim() || null };
      if (name.trim()) body.name = name.trim();
      const next = await userApi.updateProfile(body);
      onChange(next);
      setName(next.name ?? "");
      setPhone(next.phone ?? "");
      setSaved(true);
    } catch (err) {
      setError(userError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card as="form" onSubmit={save} className="space-y-4">
      <h2 className="font-medium text-fg">Details</h2>
      <div>
        <Label htmlFor={`${id}-name`}>Name</Label>
        <input id={`${id}-name`} className={inputClass} value={name} maxLength={80} autoComplete="name"
          onChange={(e) => { setName(e.target.value); setSaved(false); }} />
      </div>
      <div>
        <Label htmlFor={`${id}-email`} hint="(how you sign in; change it by adding a new sign-in method)">Email</Label>
        <input id={`${id}-email`} className={`${inputClass} text-muted`} value={profile.email} readOnly />
      </div>
      <div>
        <Label htmlFor={`${id}-phone`} hint="(optional)">Phone</Label>
        <input id={`${id}-phone`} className={inputClass} value={phone} type="tel" autoComplete="tel"
          placeholder="+91 98765 43210" maxLength={20} onChange={(e) => { setPhone(e.target.value); setSaved(false); }} />
        <p className="mt-1 text-xs text-muted">International format, starting with +. Only you see it.</p>
      </div>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      <div className="flex items-center gap-3">
        <Button type="submit" busy={busy} disabled={!dirty}>Save</Button>
        {saved && <span role="status" className="flex items-center gap-1 text-sm text-ok"><CheckIcon />Saved</span>}
      </div>
    </Card>
  );
}

function SignInMethods({ initialError }: { initialError: string | null }) {
  const [providers, setProviders] = useState<AccountProviders | null>(null);
  const [error, setError] = useState<unknown>(initialError);
  const [busy, setBusy] = useState<string | null>(null);
  const reload = useCallback(() => authApi.accountProviders().then(setProviders).catch(setError), []);
  useEffect(() => { void reload(); }, [reload]);
  if (!providers) return error ? <AuthErrorAlert error={error} /> : null;
  const has = (p: LinkedAccount["provider"]) => providers.accounts.some((a) => a.provider === p);

  async function remove(account: LinkedAccount) {
    setBusy(account.id);
    setError(null);
    try { await authApi.unlink(account.id); await reload(); } catch (e) { setError(e); } finally { setBusy(null); }
  }

  return (
    <Card>
      <h2 className="font-medium text-fg">Ways to sign in</h2>
      <div className="mt-3"><AuthErrorAlert error={error} /></div>
      <ul className="mt-2 divide-y divide-border" aria-label="Connected sign-in methods">
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
