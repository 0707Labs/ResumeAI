"use client";

import { useEffect } from "react";

/** Counts one landing view for the admin funnel: a daily number, no cookie, nothing about the visitor. */
export function LandingView() {
  useEffect(() => {
    try {
      if (!navigator.sendBeacon?.("/api/metrics/landing-view")) {
        void fetch("/api/metrics/landing-view", { method: "POST", keepalive: true }).catch(() => {});
      }
    } catch {
      /* counting must never break the page */
    }
  }, []);
  return null;
}
