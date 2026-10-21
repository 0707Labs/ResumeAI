import { redirect } from "next/navigation";

import { sessionState } from "@/lib/session";
import { signInUrl } from "@/lib/workspace";

/** The workspace needs a live session; proxy.ts only checked that a cookie exists. */
export default async function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  if ((await sessionState()) === "signed_out") redirect(signInUrl("/app"));
  return children;
}
