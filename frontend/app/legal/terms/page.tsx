import type { Metadata } from "next";
import Link from "next/link";

import { LegalDoc } from "@/components/site/LegalDoc";
import { COMPANY } from "@/lib/site";

export const metadata: Metadata = { title: "Terms of Service · Resume Tailor", alternates: { canonical: "/legal/terms" } };

export default function TermsPage() {
  return (
    <LegalDoc
      title="Terms of Service"
      updated="21 October 2026"
      intro={
        <p>
          These terms are an agreement between you and {COMPANY.legalName} (&ldquo;we&rdquo;, &ldquo;us&rdquo;), which runs{" "}
          {COMPANY.product} under its {COMPANY.lab} brand. By creating an account you agree to them and to our{" "}
          <Link href="/legal/privacy" className="text-accent underline">Privacy Policy</Link>.
        </p>
      }
      sections={[
        {
          heading: "Who can use the service",
          body: <p>You must be 18 or older and able to enter a binding contract. While we&apos;re invite-only, you need a valid invite to create an account.</p>,
        },
        {
          heading: "What the service does",
          body: (
            <>
              <p>
                {COMPANY.product} suggests changes to your resume for a job description, using only facts from your resume
                and your own answers. It also gives an ATS-style score and advice.
              </p>
              <p>
                The score is an estimate. Real applicant tracking systems differ, and we don&apos;t promise interviews,
                offers or any hiring outcome.
              </p>
            </>
          ),
        },
        {
          heading: "Your responsibilities",
          body: (
            <ul>
              <li>Only upload content you have the right to use, and keep what you submit truthful.</li>
              <li>Review every suggested change before you use it. You&apos;re responsible for what you send to employers.</li>
              <li>Keep your sign-in methods secure and tell us if you think someone else used your account.</li>
              <li>Don&apos;t misuse the service: no scraping, reverse engineering, overloading it, or using it to make false claims.</li>
            </ul>
          ),
        },
        {
          heading: "Your content",
          body: <p>You keep all rights to your resume and answers. You let us process them only to provide the service, as the Privacy Policy describes.</p>,
        },
        {
          heading: "Payments, credits and passes",
          body: (
            <>
              <p>
                Paid plans are sold by Dodo Payments, our merchant of record. Dodo processes your payment, collects any tax,
                and issues your receipt. Its terms apply to the purchase.
              </p>
              <p>
                Credits and passes are granted once your payment is confirmed. They have no cash value and can&apos;t be
                transferred. Prices are shown on the <Link href="/pricing">pricing page</Link>. Refunds follow
                our <Link href="/legal/refunds">Refund Policy</Link>.
              </p>
            </>
          ),
        },
        {
          heading: "Suspension and closing your account",
          body: <p>You can delete your account at any time from your account page. We may suspend accounts that break these terms. Where the law allows, we&apos;ll tell you why.</p>,
        },
        {
          heading: "Disclaimers and liability",
          body: <p>The service is provided &ldquo;as is&rdquo;. To the extent the law allows, our total liability to you is limited to the amount you paid us in the 12 months before the claim. Nothing in these terms limits rights you have under consumer protection law.</p>,
        },
        {
          heading: "Changes, governing law and contact",
          body: (
            <p>
              We&apos;ll tell you before material changes take effect, and you&apos;ll be asked to accept a new version.
              These terms are governed by the laws of India. For complaints, see{" "}
              <Link href="/legal/grievance">grievance redressal</Link>.
            </p>
          ),
        },
      ]}
    />
  );
}
