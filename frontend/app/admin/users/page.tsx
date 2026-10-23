"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { type Column, DataTable, Pager, Pill, day } from "@/components/admin/ui";
import { ErrorState, PageHeader } from "@/components/app/states";
import { inlineInputClass } from "@/components/ui";
import { adminApi, adminError } from "@/lib/adminApi";
import type { AdminUserPage, AdminUserRow } from "@/lib/schemas";

const STATUS_TONE = { active: "ok", suspended: "warn", deleted: "bad" } as const;
const FILTERS = {
  status: ["active", "suspended", "deleted"], role: ["user", "support", "admin", "superadmin"], plan: ["free", "credits", "pass", "pro"],
} as const;

export default function AdminUsersPage() {
  return <Suspense fallback={null}><Users /></Suspense>;
}

function Users() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const f = {
    q: params.get("q") ?? "", status: params.get("status") ?? "", role: params.get("role") ?? "",
    plan: params.get("plan") ?? "", sort: params.get("sort") ?? "created_at",
    direction: (params.get("direction") ?? "desc") as "asc" | "desc", page: Number(params.get("page") ?? 1) || 1,
  };
  const [data, setData] = useState<AdminUserPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState(f.q);
  const key = params.toString();

  useEffect(() => {
    setData(null);
    setError(null);
    adminApi.users(f).then(setData).catch((e) => setError(adminError(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- f is derived from the URL (key)
  }, [key]);

  const go = (patch: Record<string, string | number>) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) v === "" ? next.delete(k) : next.set(k, String(v));
    if (!("page" in patch)) next.delete("page");
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };
  const columns: Column<AdminUserRow>[] = [
    { key: "email", label: "User", sortable: true, render: (u) => (
      <Link href={`/admin/users/${u.id}`} className="font-medium text-accent hover:underline">
        {u.email}{u.name && <span className="block text-xs font-normal text-muted">{u.name}</span>}
      </Link>) },
    { key: "status", label: "Status", render: (u) => <Pill tone={STATUS_TONE[u.status]}>{u.status}</Pill> },
    { key: "role", label: "Role", render: (u) => (u.role === "user" ? <span className="text-muted">user</span> : <Pill>{u.role}</Pill>) },
    { key: "plan", label: "Plan", render: (u) => u.plan },
    { key: "credits_balance", label: "Credits", sortable: true, className: "text-right", render: (u) => u.credits },
    { key: "created_at", label: "Signed up", sortable: true, render: (u) => day(u.created_at) },
    { key: "last_login_at", label: "Last active", sortable: true, render: (u) => day(u.last_active_at) },
    { key: "tailorings", label: "Tailorings", sortable: true, className: "text-right", render: (u) => u.tailorings },
    { key: "downloads", label: "Downloads", className: "text-right", render: (u) => u.downloads },
    { key: "referrals", label: "Referrals", className: "text-right", render: (u) => u.referrals },
    { key: "llm_cost_usd", label: "LLM cost", sortable: true, className: "text-right", render: (u) => `$${u.llm_cost_usd.toFixed(2)}` },
  ];

  return (
    <>
      <PageHeader title="Users" intro="Metadata only: resumes and job descriptions are never shown here."
        actions={<a href={adminApi.usersCsvUrl(f)} className="inline-flex min-h-10 items-center rounded-lg border border-border-strong px-4 text-sm font-medium text-fg hover:bg-surface-2">Export CSV</a>} />
      <form role="search" className="mb-4 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); go({ q: search.trim() }); }}>
        <label htmlFor="user-search" className="sr-only">Search by email, name or id</label>
        <input id="user-search" type="search" className={`${inlineInputClass} w-64 max-w-full`} placeholder="Email, name or id"
          value={search} onChange={(e) => setSearch(e.target.value)} />
        {(Object.keys(FILTERS) as (keyof typeof FILTERS)[]).map((k) => (
          <select key={k} aria-label={`Filter by ${k}`} className={inlineInputClass} value={f[k]}
            onChange={(e) => go({ [k]: e.target.value })}>
            <option value="">Any {k}</option>
            {FILTERS[k].map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        ))}
      </form>
      {error ? <ErrorState message={error} /> : (
        <>
          <DataTable label="Users" columns={columns} rows={data?.items ?? null} sort={f.sort} direction={f.direction}
            empty="No users match." onSort={(k) => go({ sort: k, direction: f.sort === k && f.direction === "desc" ? "asc" : "desc" })} />
          {data && <Pager page={data.page} pageSize={data.page_size} total={data.total} onPage={(p) => go({ page: p })} />}
        </>
      )}
    </>
  );
}
