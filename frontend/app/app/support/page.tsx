"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { ErrorState, PageHeader, Skeleton } from "@/components/app/states";
import { CheckIcon } from "@/components/icons";
import { Button, Card, Label, inputClass } from "@/components/ui";
import type { Ticket } from "@/lib/schemas";
import { userApi, userError } from "@/lib/user";

const day = (iso: string) => new Date(iso).toLocaleDateString("en", { day: "numeric", month: "short", year: "numeric" });
type Category = Ticket["category"];
const CATEGORY: Record<Category, string> = {
  support: "Something isn't working", billing: "Billing or a payment", privacy: "My data and privacy",
  fabrication_report: "A tailored line says something untrue", feedback: "Feedback or an idea", grievance: "A complaint (grievance)",
};
const STATUS = { open: "Open", pending: "Waiting on you", closed: "Closed" } as const;

const FAQ: { q: string; a: React.ReactNode }[] = [
  { q: "Does Resume Tailor ever add experience I don't have?",
    a: "No. It only reorders and rewords what your resume already says, or what you confirm in your answers. Every rewritten line points back to the original, and a separate check blocks new tools, numbers, titles or stronger claims. If you spot one that slipped through, report it below." },
  { q: "When am I charged?",
    a: <>Tailoring and review are free to try. A clean download uses a credit, unless a pass or Pro covers it, and downloading the same tailored resume again within the re-download window is free. See <Link href="/app/billing" className="text-accent underline">Plan &amp; Billing</Link>.</> },
  { q: "How long do you keep my resume?",
    a: <>Saved base resumes stay until you delete them. Tailorings and downloaded files are cleared on a schedule; the <Link href="/legal/privacy" className="text-accent underline">Privacy Policy</Link> has the periods. You can export or delete everything from <Link href="/app/profile?tab=privacy" className="text-accent underline">Profile, Privacy</Link>.</> },
  { q: "Why is the ATS score only an estimate?",
    a: "Real applicant tracking systems differ and don't publish how they rank. Ours is a transparent breakdown (keywords, relevance, seniority, format, impact) to show what changed, not a promise of how any one system scores you." },
  { q: "How do invites work?",
    a: <>You have a set number of invites, shared between email invites and sign-ups through your link. Revoking one nobody used gives it back. See <Link href="/app/invites" className="text-accent underline">Invites &amp; Referrals</Link>.</> },
];

export default function SupportPage() {
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [category, setCategory] = useState<Category>("support");
  const formRef = useRef<HTMLDivElement>(null);
  const load = useCallback(() => {
    setLoadError(null);
    userApi.tickets().then(setTickets).catch((e) => setLoadError(userError(e)));
  }, []);
  useEffect(load, [load]);

  const startFeedback = () => {
    setCategory("feedback");
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    formRef.current?.querySelector<HTMLInputElement>("input[name=subject]")?.focus();
  };

  return (
    <>
      <PageHeader title="Support" intro="Questions, problems, ideas. A person reads every message."
        actions={<Button variant="secondary" onClick={startFeedback}>Send feedback</Button>} />
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-6">
          <ContactForm formRef={formRef} category={category} onCategory={setCategory} onSent={load} />
          <Card>
            <h2 className="font-medium text-fg">Common questions</h2>
            <div className="mt-3 divide-y divide-border">
              {FAQ.map((f) => (
                <details key={f.q} className="group py-3">
                  <summary className="cursor-pointer list-none font-medium text-fg marker:hidden">
                    <span className="mr-2 inline-block transition-transform group-open:rotate-90" aria-hidden="true">›</span>{f.q}
                  </summary>
                  <div className="mt-2 pl-5 text-sm text-muted">{f.a}</div>
                </details>
              ))}
            </div>
          </Card>
        </div>
        <div className="space-y-6">
          <Card>
            <h2 className="font-medium text-fg">Your messages</h2>
            {loadError ? <div className="mt-3"><ErrorState message={loadError} onRetry={load} /></div>
              : !tickets ? <div className="mt-3 space-y-2"><Skeleton className="h-10" /><Skeleton className="h-10" /></div>
                : tickets.length === 0 ? <p className="mt-2 text-sm text-muted">None yet. What you send shows up here.</p>
                  : (
                    <ul className="mt-2 divide-y divide-border">
                      {tickets.map((t) => (
                        <li key={t.id} className="py-2">
                          <p className="truncate text-sm font-medium text-fg">{t.subject}</p>
                          <p className="text-xs text-muted">{CATEGORY[t.category]} · {day(t.created_at)} · {STATUS[t.status]}</p>
                        </li>
                      ))}
                    </ul>
                  )}
          </Card>
          <Card>
            <h2 className="font-medium text-fg">Grievance officer</h2>
            <p className="mt-1 text-sm text-muted">For a formal complaint about how we handle your data, under Indian law.</p>
            <Link href="/legal/grievance" className="mt-2 inline-block text-sm font-medium text-accent underline">Contact the grievance officer</Link>
          </Card>
        </div>
      </div>
    </>
  );
}

function ContactForm({ formRef, category, onCategory, onSent }: {
  formRef: React.RefObject<HTMLDivElement | null>; category: Category; onCategory: (c: Category) => void; onSent: () => void;
}) {
  const id = useId();
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSent(false);
    try {
      await userApi.sendTicket({ category, subject: subject.trim(), body: body.trim() });
      setSubject("");
      setBody("");
      setSent(true);
      onSent();
    } catch (err) {
      setError(userError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div ref={formRef} className="scroll-mt-24">
    <Card as="form" onSubmit={send} className="space-y-4" aria-labelledby={`${id}-heading`}>
      <h2 id={`${id}-heading`} className="font-medium text-fg">Write to us</h2>
      <div>
        <Label htmlFor={`${id}-category`}>What&apos;s it about?</Label>
        <select id={`${id}-category`} className={inputClass} value={category} onChange={(e) => onCategory(e.target.value as Category)}>
          {(Object.keys(CATEGORY) as Category[]).map((c) => <option key={c} value={c}>{CATEGORY[c]}</option>)}
        </select>
        {category === "fabrication_report" && (
          <p className="mt-1 text-xs text-muted">Thank you. Paste the line and say what isn&apos;t true; we use these to make the checks stricter.</p>
        )}
      </div>
      <div>
        <Label htmlFor={`${id}-subject`}>Subject</Label>
        <input id={`${id}-subject`} name="subject" className={inputClass} value={subject} maxLength={150} required
          onChange={(e) => setSubject(e.target.value)} />
      </div>
      <div>
        <Label htmlFor={`${id}-body`} hint={`(${body.length}/5000)`}>Message</Label>
        <textarea id={`${id}-body`} className={`${inputClass} min-h-32`} value={body} maxLength={5000} required
          onChange={(e) => setBody(e.target.value)} />
        <p className="mt-1 text-xs text-muted">Please don&apos;t paste passwords or card numbers. We reply to your account email.</p>
      </div>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      {sent && <p role="status" className="flex items-center gap-1 text-sm text-ok"><CheckIcon />Sent. We usually reply within two working days.</p>}
      <Button type="submit" busy={busy} disabled={!subject.trim() || !body.trim()}>Send</Button>
    </Card>
    </div>
  );
}
