import type { Metadata } from "next";

import { LegalDoc } from "@/components/site/LegalDoc";
import { COMPANY } from "@/lib/site";

export const metadata: Metadata = { title: "Grievance redressal · Resume Tailor", alternates: { canonical: "/legal/grievance" } };

export default function GrievancePage() {
  const named = COMPANY.grievanceName && COMPANY.grievanceEmail;
  return (
    <LegalDoc
      title="Grievance redressal"
      updated="21 October 2026"
      intro={<p>As required by India&apos;s IT Rules, 2021 and the Digital Personal Data Protection Act, 2023, you can raise any complaint about {COMPANY.product} or your personal data with our grievance officer.</p>}
      sections={[
        {
          heading: "Grievance officer",
          body: named ? (
            <p>
              {COMPANY.grievanceName}, {COMPANY.legalName}
              <br />
              Email: <a href={`mailto:${COMPANY.grievanceEmail}`}>{COMPANY.grievanceEmail}</a>
            </p>
          ) : (
            <p>
              {COMPANY.legalName}. The officer&apos;s name and email will be published here before launch.
              {COMPANY.supportEmail && <> Until then, write to <a href={`mailto:${COMPANY.supportEmail}`}>{COMPANY.supportEmail}</a>.</>}
            </p>
          ),
        },
        {
          heading: "What to include",
          body: <p>The email on your account, what happened, and what you&apos;d like us to do. Please don&apos;t send your resume or payment card details.</p>,
        },
        {
          heading: "Timelines",
          body: <p>We acknowledge complaints within 24 hours and aim to resolve them within 15 days.</p>,
        },
        {
          heading: "If you're not satisfied",
          body: <p>For personal data complaints, you can go to the Data Protection Board of India once you&apos;ve used this process.</p>,
        },
      ]}
    />
  );
}
