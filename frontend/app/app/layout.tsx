import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { UserShell } from "@/components/app/UserShell";
import { currentUser } from "@/lib/session";
import { THEME_COOKIE } from "@/lib/theme";
import { signInUrl } from "@/lib/workspace";

/** The signed-in area needs a live session; proxy.ts only checked that a cookie exists. */
export default async function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const me = await currentUser();
  if (me === "signed_out") redirect(signInUrl("/app"));
  const saved = (await cookies()).get(THEME_COOKIE)?.value;
  const theme = saved === "light" || saved === "dark" ? saved : "system";
  return <UserShell me={typeof me === "string" ? null : me} initialTheme={theme}>{children}</UserShell>;
}
