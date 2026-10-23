"use client";

import { useEffect, useState } from "react";

import { authApi } from "@/lib/auth";

/** Staff's maintenance notice (/admin/settings), shown above every shell's header. */
export function MaintenanceBanner() {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    authApi.config().then((c) => { if (live) setText(("maintenance_banner" in c && c.maintenance_banner) || null); });
    return () => { live = false; };
  }, []);
  if (!text) return null;
  return (
    <div role="status" className="border-b border-warn/30 bg-warn-bg px-4 py-2 text-center text-sm text-warn">
      {text}
    </div>
  );
}
