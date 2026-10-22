import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Card } from "@/components/ui";
import { ROLE_LABEL, sectionsFor } from "@/lib/roles";
import { currentUser } from "@/lib/session";

export const metadata: Metadata = { title: "Admin · Resume Tailor" };

/** The admin landing page: the sections this role can open. KPIs arrive with the overview step. */
export default async function AdminHome() {
  const me = await currentUser();
  if (typeof me === "string") redirect("/signin?next=/admin");  // the layout normally catches this
  const sections = sectionsFor(me).filter((s) => s.href !== "/admin");
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-fg">Admin</h1>
        <p className="mt-1 text-sm text-muted">
          Signed in as {me.email} ({ROLE_LABEL[me.role]}). Every change you make here is recorded in the audit log.
        </p>
      </div>
      {sections.length === 0 ? (
        <Card><p className="text-sm text-muted">Nothing here is available to your role yet.</p></Card>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {sections.map((s) => (
            <li key={s.href}>
              <Link href={s.href} className="block h-full rounded-xl border border-border bg-surface p-5 hover:border-border-strong">
                <span className="font-medium text-fg">{s.label}</span>
                <span className="mt-1 block text-sm text-muted">{s.description}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
