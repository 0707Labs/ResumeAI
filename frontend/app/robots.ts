import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: ["/", "/legal/", "/pricing"], disallow: ["/api/", "/app", "/account", "/admin", "/billing"] },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
