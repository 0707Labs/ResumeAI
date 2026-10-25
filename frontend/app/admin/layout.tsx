import type { Metadata } from "next";
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";

import { AdminShell } from "@/components/admin/AdminShell";
import { Alert } from "@/components/ui";
import { isStaff } from "@/lib/roles";
import { currentUser } from "@/lib/session";
import { THEME_COOKIE } from "@/lib/theme";
import { signInUrl } from "@/lib/workspace";

// No title here: a non-staff visitor's 404 shouldn't name the area. Pages set their own.
export const metadata: Metadata = { robots: { index: false, follow: false } };

/**
 * Staff only. proxy.ts only checked for a cookie; this asks the backend who is calling.
 * Anyone without staff.access gets a 404, so the area isn't advertised. Every admin API
 * call is authorized again by FastAPI whatever this layout renders.
 */
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const me = await currentUser();
  if (me === "signed_out") redirect(signInUrl("/admin"));
  if (me === "unknown") {
    return (
      <main className="mx-auto max-w-xl px-4 py-12">
        <Alert tone="warn" title="We can't check your access right now">
          The service didn&apos;t answer. Try again in a moment.
        </Alert>
      </main>
    );
  }
  if (!isStaff(me)) notFound();
  const saved = (await cookies()).get(THEME_COOKIE)?.value;
  const theme = saved === "light" || saved === "dark" ? saved : "system";
  return <AdminShell me={me} initialTheme={theme}>{children}</AdminShell>;
}
