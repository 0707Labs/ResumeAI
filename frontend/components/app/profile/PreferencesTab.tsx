"use client";

import { useCallback, useEffect, useState } from "react";

import { EMPTY_PREFERENCES, PreferencesForm } from "@/components/app/PreferencesForm";
import { ErrorState, LoadingStatus, Skeleton } from "@/components/app/states";
import { CheckIcon } from "@/components/icons";
import { Button, Card } from "@/components/ui";
import type { PreferencesIn } from "@/lib/schemas";
import { userApi, userError } from "@/lib/user";

const day = (iso: string) => new Date(iso).toLocaleDateString("en", { day: "numeric", month: "short", year: "numeric" });

export function PreferencesTab() {
  const [prefs, setPrefs] = useState<PreferencesIn | null>(null);
  const [updated, setUpdated] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(() => {
    setLoadError(null);
    userApi.preferences().then(({ updated_at, ...p }) => { setPrefs(p); setUpdated(updated_at); })
      .catch((e) => setLoadError(userError(e)));
  }, []);
  useEffect(load, [load]);

  if (loadError) return <ErrorState message={loadError} onRetry={load} />;
  if (!prefs) return <Card className="space-y-4"><LoadingStatus />{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-10" />)}</Card>;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const { updated_at, ...p } = await userApi.savePreferences(prefs ?? EMPTY_PREFERENCES);
      setPrefs(p);
      setUpdated(updated_at);
      setSaved(true);
    } catch (e) {
      setError(userError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-6">
      <div>
        <h2 className="font-medium text-fg">What you&apos;re looking for</h2>
        <p className="mt-1 text-sm text-muted">
          Used to suggest better, never shared. {updated ? `Last saved ${day(updated)}.` : "Not saved yet."}
        </p>
      </div>
      <PreferencesForm value={prefs} onChange={(p) => { setPrefs(p); setSaved(false); }} />
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      <div className="flex items-center gap-3">
        <Button busy={busy} onClick={save}>Save preferences</Button>
        {saved && <span role="status" className="flex items-center gap-1 text-sm text-ok"><CheckIcon />Saved</span>}
      </div>
    </Card>
  );
}
