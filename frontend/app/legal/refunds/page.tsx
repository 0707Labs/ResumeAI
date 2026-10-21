import type { Metadata } from "next";
import Link from "next/link";

import { LegalDoc } from "@/components/site/LegalDoc";
import { COMPANY } from "@/lib/site";

export const metadata: Metadata = { title: "Refund Policy · Resume Tailor", alternates: { canonical: "/legal/refunds" } };

export default function RefundsPage() {
  return (
    <LegalDoc
      title="Refund Policy"
      updated="21 October 2026"
      sections={[
        {
          heading: "Who handles payments",
          body: <p>Purchases are sold and processed by Dodo Payments, our merchant of record. Dodo issues your receipt and sends any refund back to your original payment method.</p>,
        },
        {
          heading: "When you can get a refund",
          body: (
            <ul>
              <li><strong>Credit packs:</strong> a full refund if none of the pack&apos;s credits have been used, within 7 days of purchase.</li>
              <li><strong>Job Hunt Pass:</strong> a full refund if you haven&apos;t run any tailoring with it, within 7 days of purchase.</li>
              <li><strong>Partly used purchases:</strong> we may refund the unused share at our discretion.</li>
              <li><strong>Something went wrong on our side:</strong> if a run fails because of us, the credit is returned automatically. If you were charged twice, the duplicate is refunded in full.</li>
            </ul>
          ),
        },
        {
          heading: "How to ask",
          body: (
            <p>
              Email {COMPANY.supportEmail ? <a href={`mailto:${COMPANY.supportEmail}`}>{COMPANY.supportEmail}</a> : "our support team"}{" "}
              with the email on your account and your receipt or payment ID. You can find those on your billing page. We
              reply within 5 working days.
            </p>
          ),
        },
        {
          heading: "After a refund",
          body: <p>Refunded credits or passes are removed from your account. Refunds usually reach you in 5 to 10 working days, depending on your bank. Card-network dispute rules still apply.</p>,
        },
        {
          heading: "Complaints",
          body: <p>If you&apos;re unhappy with how a refund was handled, see <Link href="/legal/grievance">grievance redressal</Link>.</p>,
        },
      ]}
    />
  );
}
