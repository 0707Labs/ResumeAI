import Link from "next/link";

import { COMPANY } from "@/lib/site";

/** Footer for the public pages: legal links, grievance contact, who runs this. */
export function SiteFooter() {
  const link = "rounded hover:text-fg hover:underline";
  return (
    <footer className="border-t border-border bg-surface">
      <div className="mx-auto grid max-w-6xl gap-6 px-4 py-8 text-sm text-muted sm:px-6 md:grid-cols-[1fr_auto]">
        <div className="space-y-2">
          <p className="font-semibold text-fg">{COMPANY.product}</p>
          <p>A product of {COMPANY.lab}, {COMPANY.legalName}</p>
          <p>
            Grievance officer:{" "}
            {COMPANY.grievanceName && COMPANY.grievanceEmail ? (
              <>
                {COMPANY.grievanceName},{" "}
                <a href={`mailto:${COMPANY.grievanceEmail}`} className={`${link} underline`}>{COMPANY.grievanceEmail}</a>
              </>
            ) : (
              <Link href="/legal/grievance" className={`${link} underline`}>how to raise a concern</Link>
            )}
          </p>
          <p>© {new Date().getFullYear()} {COMPANY.legalName}</p>
        </div>
        <nav aria-label="Legal">
          <ul className="flex flex-wrap gap-x-5 gap-y-2 md:flex-col">
            <li><Link href="/legal/terms" className={link}>Terms of Service</Link></li>
            <li><Link href="/legal/privacy" className={link}>Privacy Policy</Link></li>
            <li><Link href="/legal/refunds" className={link}>Refund Policy</Link></li>
            <li><Link href="/legal/grievance" className={link}>Grievance redressal</Link></li>
            <li><Link href="/pricing" className={link}>Pricing</Link></li>
          </ul>
        </nav>
      </div>
    </footer>
  );
}
