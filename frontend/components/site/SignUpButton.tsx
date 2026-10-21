"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useId, useRef, useState } from "react";

import { Button, Label, inputClass } from "@/components/ui";

/** Read by /signup/invite to pre-fill the code typed here. Only this tab, cleared once used. */
export const INVITE_CODE_KEY = "rt:invite-code";

const LINK_CLS = {
  primary: "bg-accent text-accent-fg hover:bg-accent-hover",
  secondary: "border border-border-strong bg-surface text-fg hover:bg-surface-2",
} as const;

/**
 * "Sign up". Open signup: a link to /signup. Invite-only: a dialog that takes an
 * invite code (then /signup, where the code is pre-filled after sign-in) or sends
 * the visitor to the waitlist.
 */
export function SignUpButton({ inviteOnly, label = "Sign up", variant = "primary", className = "" }: {
  inviteOnly: boolean;
  label?: string;
  variant?: keyof typeof LINK_CLS;
  className?: string;
}) {
  const cls = `inline-flex min-h-9 items-center justify-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium ${LINK_CLS[variant]} ${className}`;
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);

  if (!inviteOnly) return <Link href="/signup" className={cls}>{label}</Link>;

  const show = () => {
    setOpen(true);
    const d = dialogRef.current;
    if (d && typeof d.showModal === "function") d.showModal();
    else d?.setAttribute("open", "");
  };
  const close = () => {
    setOpen(false);
    const d = dialogRef.current;
    if (d && typeof d.close === "function") d.close();
    else d?.removeAttribute("open");
  };

  return (
    <>
      <button type="button" className={cls} aria-haspopup="dialog" onClick={show}>{label}</button>
      <dialog ref={dialogRef} onClose={() => setOpen(false)} aria-labelledby="invite-dialog-title"
        className="m-auto w-[calc(100%-2rem)] max-w-md rounded-2xl border border-border bg-surface p-0 text-fg backdrop:bg-black/50">
        {open && <InviteForm onCancel={close} />}
      </dialog>
    </>
  );
}

function InviteForm({ onCancel }: { onCancel: () => void }) {
  const router = useRouter();
  const id = useId();
  const [code, setCode] = useState("");
  const [error, setError] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = code.trim();
    if (!trimmed) {
      setError("Enter your invite code, or join the waitlist below.");
      return;
    }
    try { sessionStorage.setItem(INVITE_CODE_KEY, trimmed); } catch { /* storage blocked: they'll type it again */ }
    router.push("/signup");
  };

  return (
    <div className="space-y-5 p-6">
      <div>
        <h2 id="invite-dialog-title" className="text-xl font-semibold tracking-tight">Resume Tailor is invite-only for now</h2>
        <p className="mt-1 text-sm text-muted">
          We&apos;re letting people in gradually. If someone sent you an invite, enter it here and we&apos;ll
          ask for it again after you sign in.
        </p>
      </div>
      <form onSubmit={submit} noValidate className="space-y-3">
        <Label htmlFor={`${id}-code`} hint="(like ABCD-EFGH-JKLM)">Invite code</Label>
        <input id={`${id}-code`} autoComplete="off" spellCheck={false} value={code} autoFocus
          aria-invalid={!!error || undefined} aria-describedby={error ? `${id}-err` : undefined}
          onChange={(e) => { setCode(e.target.value); setError(""); }} className={inputClass} />
        {error && <p id={`${id}-err`} className="text-sm text-bad">{error}</p>}
        <div className="flex flex-wrap gap-2">
          <Button type="submit">Continue to sign up</Button>
          <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        </div>
      </form>
      <p className="border-t border-border pt-4 text-sm text-muted">
        No invite yet?{" "}
        <Link href="/waitlist" className="font-medium text-accent underline">Join the waitlist</Link> and we&apos;ll
        email you when there&apos;s room.
      </p>
    </div>
  );
}
