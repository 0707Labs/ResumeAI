import Link from "next/link";

import { COMPANY } from "@/lib/site";

const link = "hover:text-fg hover:underline";

/** Footer for the public pages: product and legal links, contacts, who runs this. */
export function SiteFooter() {
  return (
    <footer className="border-t border-border bg-surface">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-12 text-sm text-muted sm:px-6 md:grid-cols-[1.6fr_1fr_1fr_1.3fr]">
        <div className="space-y-3">
          <p className="text-base font-semibold text-fg">{COMPANY.product}</p>
          <p className="max-w-xs leading-relaxed">Tailor your resume to any job, without ever inventing experience.</p>
          <p>A product of {COMPANY.lab}, {COMPANY.legalName}</p>
        </div>
        <nav aria-label="Product">
          <p className="font-semibold text-fg">Product</p>
          <ul className="mt-3 space-y-2">
            <li><Link href="/#how-it-works" className={link}>How it works</Link></li>
            <li><Link href="/#sample" className={link}>Sample</Link></li>
            <li><Link href="/pricing" className={link}>Pricing</Link></li>
            <li><Link href="/signin" className={link}>Sign in</Link></li>
          </ul>
        </nav>
        <nav aria-label="Legal">
          <p className="font-semibold text-fg">Legal</p>
          <ul className="mt-3 space-y-2">
            <li><Link href="/legal/terms" className={link}>Terms of Service</Link></li>
            <li><Link href="/legal/privacy" className={link}>Privacy Policy</Link></li>
            <li><Link href="/legal/refunds" className={link}>Refund Policy</Link></li>
            <li><Link href="/legal/grievance" className={link}>Grievance redressal</Link></li>
          </ul>
        </nav>
        <div>
          <p className="font-semibold text-fg">Contact</p>
          <ul className="mt-3 space-y-2">
            {COMPANY.supportEmail && (
              <li>Support: <a href={`mailto:${COMPANY.supportEmail}`} className={`${link} underline`}>{COMPANY.supportEmail}</a></li>
            )}
            <li>
              Grievance officer:{" "}
              {COMPANY.grievanceName && COMPANY.grievanceEmail ? (
                <>{COMPANY.grievanceName}, <a href={`mailto:${COMPANY.grievanceEmail}`} className={`${link} underline`}>{COMPANY.grievanceEmail}</a></>
              ) : (
                <Link href="/legal/grievance" className={`${link} underline`}>how to raise a concern</Link>
              )}
            </li>
          </ul>
        </div>
      </div>
      <div className="border-t border-border">
        <p className="mx-auto max-w-6xl px-4 py-5 text-xs text-muted sm:px-6">
          © {new Date().getFullYear()} {COMPANY.legalName}. No analytics, no tracking cookies.
        </p>
      </div>
    </footer>
  );
}
