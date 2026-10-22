"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DataTable, Pager, Pill, when } from "@/components/admin/ui";
import { ErrorState, PageHeader } from "@/components/app/states";
import { inlineInputClass } from "@/components/ui";
import { adminApi, adminError } from "@/lib/adminApi";
import type { AdminTicketPage } from "@/lib/schemas";

const CATEGORY = { support: "Support", billing: "Billing", privacy: "Privacy", fabrication_report: "Untrue line",
  feedback: "Feedback", grievance: "Grievance" } as const;
const STATUS = { open: ["Open", "warn"], pending: ["Waiting on user", "neutral"], closed: ["Closed", "ok"] } as const;

/** The contact-form inbox: oldest waiting first. */
export default function AdminSupportPage() {
  const [f, setF] = useState({ status: "active", category: "", assignee: "", q: "", page: 1 });
  const [data, setData] = useState<AdminTicketPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    setData(null);
    adminApi.tickets(f).then(setData).catch((e) => setError(adminError(e)));
  }, [f]);
  useEffect(load, [load]);
  const set = (patch: Partial<typeof f>) => setF((x) => ({ ...x, ...patch, page: patch.page ?? 1 }));
  return (
    <>
      <PageHeader title="Support" intro="Messages from the contact form. Replies go to the person by email." />
      <div className="mb-4 flex flex-wrap gap-2">
        <select aria-label="Status" className={inlineInputClass} value={f.status} onChange={(e) => set({ status: e.target.value })}>
          <option value="active">Open or waiting</option><option value="open">Open</option><option value="pending">Waiting on user</option>
          <option value="closed">Closed</option><option value="">All</option>
        </select>
        <select aria-label="Category" className={inlineInputClass} value={f.category} onChange={(e) => set({ category: e.target.value })}>
          <option value="">Any category</option>{Object.entries(CATEGORY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select aria-label="Assignee" className={inlineInputClass} value={f.assignee} onChange={(e) => set({ assignee: e.target.value })}>
          <option value="">Anyone</option><option value="me">Mine</option><option value="none">Unassigned</option>
        </select>
        <input type="search" aria-label="Search subject or email" placeholder="Subject or email" className={`${inlineInputClass} w-56 max-w-full`}
          value={f.q} onChange={(e) => set({ q: e.target.value })} />
      </div>
      {error ? <ErrorState message={error} onRetry={load} /> : (
        <>
          <DataTable label="Tickets" rows={data?.items ?? null} empty="Nothing waiting. Nice." columns={[
            { key: "subject", label: "Subject", render: (t) => <Link href={`/admin/support/${t.id}`} className="font-medium text-accent hover:underline">{t.subject}</Link> },
            { key: "from", label: "From", render: (t) => t.email },
            { key: "category", label: "Category", render: (t) => CATEGORY[t.category] },
            { key: "status", label: "Status", render: (t) => <Pill tone={STATUS[t.status][1]}>{STATUS[t.status][0]}</Pill> },
            { key: "assignee", label: "Assignee", render: (t) => t.assignee_email ?? "—" },
            { key: "updated", label: "Last activity", render: (t) => when(t.updated_at) },
          ]} />
          {data && <Pager page={data.page} pageSize={data.page_size} total={data.total} onPage={(p) => set({ page: p })} />}
        </>
      )}
    </>
  );
}
