"use client";

import { type FormEvent, useState } from "react";

import { Alert, Button, Label, inputClass } from "@/components/ui";

import { AuthErrorAlert } from "./AuthCard";

/** Ask for an email address, call `send`, then say "check your inbox". */
export function EmailForm({ id, label, button, send, initial = "", sentTitle = "Check your email" }: {
  id: string;
  label: string;
  button: string;
  send: (email: string) => Promise<unknown>;
  initial?: string;
  sentTitle?: string;
}) {
  const [email, setEmail] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await send(email.trim());
      setSentTo(email.trim());
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (sentTo) {
    return (
      <Alert tone="ok" title={sentTitle} role="status">
        We sent a link to <strong>{sentTo}</strong>. It works for 15 minutes, in this browser.{" "}
        <button type="button" className="font-medium underline" onClick={() => setSentTo(null)}>Use a different address</button>
      </Alert>
    );
  }
  return (
    <form onSubmit={submit} className="space-y-3" noValidate>
      <div>
        <Label htmlFor={id}>{label}</Label>
        <input id={id} type="email" autoComplete="email" required value={email}
          onChange={(e) => setEmail(e.target.value)} className={inputClass} />
      </div>
      <AuthErrorAlert error={error} />
      <Button type="submit" variant="secondary" className="w-full" busy={busy} disabled={!email.includes("@")}>
        {button}
      </Button>
    </form>
  );
}
