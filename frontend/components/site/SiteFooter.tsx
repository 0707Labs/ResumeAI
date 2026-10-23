import Link from "next/link";

import { BrandLogo } from "@/components/BrandLogo";
import { COMPANY, SITE_NAV } from "@/lib/site";

const link = "inline-flex min-h-8 items-center hover:text-fg hover:underline underline-offset-4";
const heading = "text-xs font-semibold uppercase tracking-[0.08em] text-fg";

export const LEGAL_LINKS = [
  { href: "/legal/terms", label: "Terms of Service" },
  { href: "/legal/privacy", label: "Privacy Policy" },
  { href: "/legal/refunds", label: "Refund Policy" },
  { href: "/legal/grievance", label: "Grievance redressal" },
] as const;

/** Footer for the public pages: product and legal links, contacts, who runs this. */
export function SiteFooter() {
  return (
    <footer className="border-t border-border bg-surface text-sm text-muted">
      <div className="mx-auto grid max-w-(--container) gap-10 px-(--gutter) py-12 sm:grid-cols-2 md:grid-cols-[1.5fr_1fr_1fr_1.4fr]">
        <div className="space-y-3">
          <Link href="/" className="inline-block text-base font-semibold text-fg"><BrandLogo /></Link>
          <p className="max-w-xs">Tailor your resume to any job, without ever inventing experience.</p>
        </div>
        <nav aria-label="Product">
          <p className={heading}>Product</p>
          <ul className="mt-3 space-y-1">
            {SITE_NAV.map((item) => <li key={item.href}><Link href={item.href} className={link}>{item.label}</Link></li>)}
            <li><Link href="/#sample" className={link}>Sample</Link></li>
            <li><Link href="/signin" className={link}>Sign in</Link></li>
          </ul>
        </nav>
        <nav aria-label="Legal">
          <p className={heading}>Legal</p>
          <ul className="mt-3 space-y-1">
            {LEGAL_LINKS.map((item) => <li key={item.href}><Link href={item.href} className={link}>{item.label}</Link></li>)}
          </ul>
        </nav>
        <div>
          <p className={heading}>Contact</p>
          <dl className="mt-3 space-y-3">
            {COMPANY.supportEmail && (
              <div>
                <dt className="text-fg">Support</dt>
                <dd><a href={`mailto:${COMPANY.supportEmail}`} className={`${link} underline`}>{COMPANY.supportEmail}</a></dd>
              </div>
            )}
            <div>
              <dt className="text-fg">Grievance officer</dt>
              <dd>
                {COMPANY.grievanceName && COMPANY.grievanceEmail ? (
                  <>{COMPANY.grievanceName},{" "}
                    <a href={`mailto:${COMPANY.grievanceEmail}`} className={`${link} underline`}>{COMPANY.grievanceEmail}</a></>
                ) : (
                  <Link href="/legal/grievance" className={`${link} underline`}>How to raise a concern</Link>
                )}
              </dd>
            </div>
          </dl>
        </div>
      </div>
      <div className="border-t border-dashed border-border-strong">
        <div className="mx-auto flex max-w-(--container) flex-wrap items-center justify-between gap-x-6 gap-y-2 px-(--gutter) py-5 text-xs">
          <p className="font-medium text-fg">A product of {COMPANY.lab}, {COMPANY.legalName}</p>
          <p>© {new Date().getFullYear()} {COMPANY.legalName}. No analytics, no tracking cookies.</p>
        </div>
      </div>
    </footer>
  );
}
