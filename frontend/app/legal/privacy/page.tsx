import type { Metadata } from "next";
import Link from "next/link";

import { LegalDoc } from "@/components/site/LegalDoc";
import { COMPANY } from "@/lib/site";

export const metadata: Metadata = { title: "Privacy Policy · Resume Tailor", alternates: { canonical: "/legal/privacy" } };

export default function PrivacyPage() {
  return (
    <LegalDoc
      title="Privacy Policy"
      updated="21 October 2026"
      intro={
        <p>
          {COMPANY.legalName} is the data fiduciary for {COMPANY.product}. This policy says what we collect, why, who
          else processes it, and the choices you have under India&apos;s Digital Personal Data Protection Act, 2023 and
          other laws that apply to you.
        </p>
      }
      sections={[
        {
          heading: "What we collect",
          body: (
            <ul>
              <li><strong>Account:</strong> your email, the sign-in methods you connect (Google, GitHub or email link), and your account status.</li>
              <li><strong>Consent records:</strong> which version of these terms you accepted, your 18+ confirmation, and any optional research consent, with a one-way hash of the IP address used.</li>
              <li><strong>Billing:</strong> your purchases, credit and pass history, and a customer reference from Dodo Payments. We never see or store card details.</li>
              <li><strong>Usage records:</strong> when an analysis runs, what it cost us in AI usage, and each download (format and what paid for it). These records and our logs don&apos;t contain your resume text.</li>
              <li><strong>Waitlist:</strong> your email, if you join it.</li>
            </ul>
          ),
        },
        {
          heading: "Your resume and job descriptions",
          body: (
            <>
              <p>
                Your resume, the job description and your answers are sent to our service to produce results. Your work in
                progress is kept in your browser tab (session storage) and cleared when you close it or choose Clear all.
                When you start a tailoring, we keep the parsed resume and job description with it on our servers, so AI
                use and the downloaded file are tied to exactly what you submitted. When you download, we keep the
                final resume behind that download for the re-download period. [Retention period to be decided.]
              </p>
              <p>
                Each file you download carries a reference number in its document properties (for example
                &ldquo;rt-dl-&hellip;&rdquo;). It contains no personal data, but lets us link a copy of the file back to
                the download, and so to your account, if it&apos;s shared publicly without permission. The preview before
                payment is a watermarked image built on our servers.
              </p>
              <p>
                When AI features are on, this text is sent to Anthropic, which provides the Claude models we use, to
                generate suggestions. Anthropic processes it on our behalf and doesn&apos;t use it to train its models.
              </p>
            </>
          ),
        },
        {
          heading: "Who else processes your data",
          body: (
            <ul>
              <li>Anthropic: AI processing of resume and job text.</li>
              <li>Dodo Payments (merchant of record): checkout, tax, receipts and refunds. It receives what you enter at checkout.</li>
              <li>Google and GitHub: only if you sign in with them. We receive your verified email and an account ID. We never store their access tokens.</li>
              <li>Our hosting and email providers, to run the service and send sign-in links.</li>
            </ul>
          ),
        },
        {
          heading: "Cookies",
          body: <p>We use only cookies needed to run the service: your sign-in session, security tokens (CSRF and sign-in flow), and your light or dark theme choice. We don&apos;t use analytics, advertising or tracking cookies.</p>,
        },
        {
          heading: "How long we keep data",
          body: <p>Account data is kept while your account is open. When you delete your account, we remove your sign-in methods and personal details. We keep payment and consent records for as long as tax and other laws require.</p>,
        },
        {
          heading: "Your rights",
          body: (
            <p>
              You can access, correct or delete your data, withdraw optional consents, and nominate someone to act for you.
              Most of this is in your account page. For anything else, contact our grievance officer
              (see <Link href="/legal/grievance">grievance redressal</Link>). You can also complain to the Data Protection
              Board of India.
            </p>
          ),
        },
        {
          heading: "Changes",
          body: <p>If we change this policy in a way that affects you, we&apos;ll tell you and ask again where your consent is needed.</p>,
        },
      ]}
    />
  );
}
