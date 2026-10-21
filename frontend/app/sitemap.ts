import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/site";

export default function sitemap(): MetadataRoute.Sitemap {
  return ["", "/pricing", "/legal/terms", "/legal/privacy", "/legal/refunds", "/legal/grievance"]
    .map((path) => ({ url: `${SITE_URL}${path || "/"}` }));
}
