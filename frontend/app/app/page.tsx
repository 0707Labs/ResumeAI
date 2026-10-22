import { redirect } from "next/navigation";

import { currentUser } from "@/lib/session";

/** /app: first sign-in goes through the welcome steps once, then always to the dashboard. */
export default async function AppHome() {
  const me = await currentUser();
  redirect(typeof me !== "string" && !me.onboarded ? "/app/welcome" : "/app/dashboard");
}
