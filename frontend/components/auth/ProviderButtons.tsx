"use client";

import { providerStartUrl } from "@/lib/auth";

/*
 * Brand marks are used unmodified, as each provider's guidelines require:
 * - Google: the standard four-colour "G" on the light (#FFFFFF, #747775 border)
 *   or dark (#131314, #8E918F border) button, 40px tall, Roboto Medium 14px,
 *   label "Continue with Google". Roboto is used when installed; we load no
 *   third-party fonts (no network calls except our own origin).
 * - GitHub: the Invertocat mark in one solid colour (white on dark, black on light).
 */

export function GoogleMark() {
  return (
    <svg viewBox="0 0 48 48" width="20" height="20" aria-hidden="true" focusable="false">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

export function GitHubMark() {
  return (
    <svg viewBox="0 0 16 16" width="20" height="20" aria-hidden="true" focusable="false" fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

const BASE =
  "flex h-10 w-full items-center justify-center gap-2.5 rounded-[4px] px-3 text-sm font-medium [font-family:Roboto,ui-sans-serif,system-ui,sans-serif]";

const STYLE = {
  google: { cls: "border border-google-border bg-google-bg text-google-fg", Mark: GoogleMark, name: "Google" },
  github: { cls: "bg-github-bg text-github-fg", Mark: GitHubMark, name: "GitHub" },
} as const;

/** "Continue with Google/GitHub". A plain link: OAuth needs a full-page redirect.
 * When the provider isn't configured the button is disabled and says so. */
export function ProviderButton({ provider, available, next, link = false }: {
  provider: "google" | "github";
  available: boolean;
  next?: string;
  link?: boolean;
}) {
  const { cls, Mark, name } = STYLE[provider];
  const label = link ? `Connect ${name}` : `Continue with ${name}`;
  if (!available) {
    return (
      <span aria-disabled="true" className={`${BASE} ${cls} cursor-not-allowed opacity-50`}>
        <Mark />
        {label}
        <span className="sr-only"> (Provider unavailable)</span>
      </span>
    );
  }
  return (
    <a href={providerStartUrl(provider, { next, link })} className={`${BASE} ${cls} hover:opacity-90`}>
      <Mark />
      {label}
    </a>
  );
}

export function ProviderButtons({ available, next }: {
  available: { google: boolean; github: boolean } | null;
  next?: string;
}) {
  return (
    <div className="space-y-3">
      <ProviderButton provider="google" available={available?.google ?? false} next={next} />
      <ProviderButton provider="github" available={available?.github ?? false} next={next} />
      {available && !available.google && !available.github && (
        <p className="text-xs text-muted">Provider unavailable: Google and GitHub sign-in aren&apos;t set up here yet.</p>
      )}
    </div>
  );
}
