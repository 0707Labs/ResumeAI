import type { Metadata, Viewport } from "next";
import { cookies } from "next/headers";

import { AppShell } from "@/components/AppShell";
import { THEME_COOKIE } from "@/lib/theme";

import "./globals.css";

export const metadata: Metadata = {
  title: "Resume Tailor",
  description: "Tailor your resume to a job honestly. You approve every change.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f8fb" },
    { media: "(prefers-color-scheme: dark)", color: "#0b1220" },
  ],
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // An explicit light/dark choice lives in a cookie so the server renders it
  // from the first byte (no flash, no inline script). Absent = follow the system.
  const saved = (await cookies()).get(THEME_COOKIE)?.value;
  const theme = saved === "light" || saved === "dark" ? saved : undefined;
  return (
    <html lang="en" data-theme={theme} suppressHydrationWarning>
      <body className="min-h-screen font-sans antialiased">
        <AppShell initialTheme={theme ?? "system"}>{children}</AppShell>
      </body>
    </html>
  );
}
