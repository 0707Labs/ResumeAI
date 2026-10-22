"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { EmptyState, ErrorState, LoadingStatus, Skeleton } from "@/components/app/states";
import { AuthErrorAlert } from "@/components/auth/AuthCard";
import { Button, Card } from "@/components/ui";
import { authApi } from "@/lib/auth";
import type { Consents } from "@/lib/schemas";
import { userApi, userError } from "@/lib/user";

const when = (iso: string) => new Date(iso).toLocaleString("en", { dateStyle: "medium", timeStyle: "short" });
const PURPOSE: Record<Consents["history"][number]["purpose"], string> = {
  service: "Terms of Service and Privacy Policy", age_18_plus: "Confirmed 18 or older",
  research: "Help improve the product (optional)", waitlist: "Waitlist emails",
};
const METHOD: Record<string, string> = {
  signup: "at sign-up", account_settings: "in your settings", reconsent: "when the terms changed",
  admin: "by our team", deletion: "when the account was deleted",
};

export function PrivacyTab() {
  const [consents, setConsents] = useState<Consents | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const load = useCallback(() => {
    setLoadError(null);
    userApi.consents().then(setConsents).catch((e) => setLoadError(userError(e)));
  }, []);
  useEffect(load, [load]);

  return (
    <div className="space-y-6">
      {loadError ? <ErrorState message={loadError} onRetry={load} /> : !consents ? (
        <Card className="space-y-3"><LoadingStatus label="Loading your consents" /><Skeleton className="h-6 w-48" /><Skeleton className="h-16" /></Card>
      ) : (
        <>
          <ResearchCard consents={consents} onChange={setConsents} />
          <HistoryCard consents={consents} />
        </>
      )}
      <ExportCard />
      <DeleteAccount />
    </div>
  );
}

function ResearchCard({ consents, onChange }: { consents: Consents; onChange: (c: Consents) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toggle = async () => {
    setBusy(true);
    setError(null);
    try { onChange(await userApi.setResearch(!consents.research)); } catch (e) { setError(userError(e)); } finally { setBusy(false); }
  };
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-lg">
          <h2 className="font-medium text-fg" id="research-label">Help improve the product</h2>
          <p className="mt-1 text-sm text-muted">
            Optional. Lets us study anonymised tailoring results to make suggestions better. Turning it off stops this
            from now on; it never affects what you can do here.
          </p>
        </div>
        <button type="button" role="switch" aria-checked={consents.research} aria-labelledby="research-label"
          disabled={busy || (!consents.research && !consents.research_available)} onClick={toggle}
          className={`relative h-7 w-12 shrink-0 rounded-full transition-colors disabled:opacity-50 ${consents.research ? "bg-accent" : "bg-border-strong"}`}>
          <span aria-hidden="true" className={`absolute top-1 h-5 w-5 rounded-full bg-surface shadow transition-all ${consents.research ? "left-6" : "left-1"}`} />
        </button>
      </div>
      <p className="mt-2 text-sm text-fg">{consents.research ? "On" : "Off"}</p>
      {error && <p role="alert" className="mt-2 text-sm text-bad">{error}</p>}
    </Card>
  );
}

function HistoryCard({ consents }: { consents: Consents }) {
  return (
    <Card>
      <h2 className="font-medium text-fg">Consent history</h2>
      <p className="mt-1 text-sm text-muted">Every consent you gave or withdrew, with the version of the notice you saw.</p>
      {consents.history.length === 0 ? (
        <div className="mt-4"><EmptyState title="Nothing recorded yet" /></div>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[32rem] text-left text-sm">
            <thead className="text-xs text-muted">
              <tr><th scope="col" className="py-2 pr-3 font-medium">What</th><th scope="col" className="py-2 pr-3 font-medium">Choice</th>
                <th scope="col" className="py-2 pr-3 font-medium">Notice</th><th scope="col" className="py-2 font-medium">When</th></tr>
            </thead>
            <tbody className="divide-y divide-border">
              {consents.history.map((h, i) => (
                <tr key={`${h.at}-${i}`}>
                  <td className="py-2 pr-3 text-fg">{PURPOSE[h.purpose]}</td>
                  <td className="py-2 pr-3 text-fg">{h.action === "granted" ? "Given" : "Withdrawn"} {METHOD[h.method] ?? ""}</td>
                  <td className="py-2 pr-3"><Link href={h.notice_url} className="text-accent underline-offset-2 hover:underline">v{h.notice_version}</Link></td>
                  <td className="py-2 text-muted">{when(h.at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function ExportCard() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  return (
    <Card>
      <h2 className="font-medium text-fg">Export my data</h2>
      <p className="mt-1 text-sm text-muted">
        A JSON file with your account, saved resumes and versions, tailorings we still keep, downloads, credits,
        payments and consents. Up to three exports an hour.
      </p>
      {error && <p role="alert" className="mt-2 text-sm text-bad">{error}</p>}
      {done && <p role="status" className="mt-2 text-sm text-ok">Your file is downloading.</p>}
      <Button variant="secondary" className="mt-4" busy={busy} onClick={async () => {
        setBusy(true); setError(null); setDone(false);
        try { await userApi.exportData(); setDone(true); } catch (e) { setError(userError(e)); } finally { setBusy(false); }
      }}>Download my data</Button>
    </Card>
  );
}

function DeleteAccount() {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <Card>
      <h2 className="font-medium text-fg">Delete account</h2>
      <p className="mt-1 text-sm text-muted">
        This removes your account, sign-in methods, picture, saved resumes and preferences now. Tailorings and
        downloads are cleared on their usual schedule. You&apos;d need a new invite to come back.
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
