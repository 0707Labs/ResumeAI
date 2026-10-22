import type { Metadata } from "next";
import Link from "next/link";

import { ArrowRightIcon, CheckIcon, ErrorIcon, FileIcon, ShieldIcon, UploadIcon } from "@/components/icons";
import { PublicPage } from "@/components/site/PublicPage";
import { SignUpButton } from "@/components/site/SignUpButton";
import { freePoints, planPoints, priceList } from "@/lib/billing";
import type { Plans } from "@/lib/schemas";
import { COMPANY, SITE_URL, getPlans, getPublicConfig } from "@/lib/site";

const TITLE = "Resume Tailor: tailor your resume to any job, honestly";
const DESCRIPTION =
  "Tailor your resume to any job description without inventing experience. Every change cites your original " +
  "resume, a verifier blocks new claims, and you approve each edit. See an ATS-style score and mentor advice.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  metadataBase: new URL(SITE_URL),
  alternates: { canonical: "/" },
  openGraph: { title: TITLE, description: DESCRIPTION, url: "/", siteName: COMPANY.product, type: "website" },
  twitter: { card: "summary", title: TITLE, description: DESCRIPTION },
};

const FAQ: { q: string; a: string }[] = [
  {
    q: "Will it add skills or experience I don't have?",
    a: "No. Every rewritten line has to point at the line of your resume it came from, and a separate verifier " +
      "blocks new tools, numbers, titles, employers or stronger claims than your original. If the job asks for " +
      "something your resume doesn't show, we ask you about it instead of filling it in.",
  },
  {
    q: "Does a high score mean I'll get past every ATS?",
    a: "No. Our score is a transparent estimate built from keyword coverage, relevance, title fit, formatting and " +
      "quantified impact, with the full breakdown shown. Real applicant tracking systems differ from each other, " +
      "and a person reads your resume in the end.",
  },
  {
    q: "What happens to my resume?",
    a: "Your resume and the job description are sent to our service to produce the analysis, and kept with that " +
      "tailoring on our servers so the download matches exactly what you reviewed. Your work in progress stays in " +
      "your browser tab. We don't use analytics or tracking. The Privacy Policy has the details, including how AI " +
      "processing works and how long anything is kept.",
  },
  {
    q: "What does a credit get me?",
    a: "One credit is one clean download (DOCX or PDF) of a tailored resume, and re-downloading that same resume " +
      "is free for a week. Tailoring, review and the watermarked preview are free within a monthly allowance. " +
      "The Job Hunt Pass covers downloads for 30 days. There's no subscription unless you choose one.",
  },
  {
    q: "Can I get a refund?",
    a: "Payments are handled by Dodo Payments, our merchant of record, which also issues your receipt. The Refund " +
      "Policy explains when unused credits and passes can be refunded and how to ask.",
  },
  {
    q: "Why is it invite-only?",
    a: "We're opening up gradually so we can keep quality high and costs honest. Join the waitlist and we'll " +
      "email you when there's room, or use an invite from someone who already has an account.",
  },
];

export default async function LandingPage() {
  const [{ invite_only: inviteOnly }, plans] = await Promise.all([getPublicConfig(), getPlans()]);
  const faq = inviteOnly ? FAQ : FAQ.filter((f) => !f.q.startsWith("Why is it invite-only"));
  return (
    <PublicPage>
      <script type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd(faq)).replace(/</g, "\\u003c") }} />
      <Hero inviteOnly={inviteOnly} />
      <HowItWorks />
      <Honesty />
      <Sample />
      <Pricing plans={plans} inviteOnly={inviteOnly} />
      <Faq items={faq} />
    </PublicPage>
  );
}

function faqJsonLd(items: { q: string; a: string }[]) {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: items.map(({ q, a }) => ({ "@type": "Question", name: q, acceptedAnswer: { "@type": "Answer", text: a } })),
  };
}

function Section({ id, title, intro, children, tint = false }: {
  id: string;
  title: string;
  intro?: string;
  children: React.ReactNode;
  tint?: boolean;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className={`scroll-mt-4 ${tint ? "bg-surface" : ""}`}>
      <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6 sm:py-20">
        <h2 id={`${id}-title`} className="text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h2>
        {intro && <p className="mt-3 max-w-2xl text-muted">{intro}</p>}
        <div className="mt-8">{children}</div>
      </div>
    </section>
  );
}

function Hero({ inviteOnly }: { inviteOnly: boolean }) {
  return (
    <section aria-labelledby="hero-title" className="mx-auto max-w-6xl px-4 pb-14 pt-14 sm:px-6 sm:pt-24">
      <p className="inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-3 py-1 text-sm font-medium text-accent">
        <ShieldIcon /> Honest by design
      </p>
      <h1 id="hero-title" className="mt-5 max-w-3xl text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
        Tailor your resume to any job, without ever inventing experience
      </h1>
      <p className="mt-5 max-w-2xl text-lg text-muted">
        Upload your resume and paste the job description. We reorder and reword what&apos;s already true, ask you
        about the gaps, and show you every change before it counts. You approve each edit.
      </p>
      <div className="mt-8 flex flex-wrap items-center gap-3">
        {inviteOnly ? (
          <Link href="/waitlist" className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-accent px-5 py-2.5 font-medium text-accent-fg hover:bg-accent-hover">
            Request an invite <ArrowRightIcon />
          </Link>
        ) : (
          <Link href="/signup" className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-accent px-5 py-2.5 font-medium text-accent-fg hover:bg-accent-hover">
            Get started free <ArrowRightIcon />
          </Link>
        )}
        <Link href="#sample" className="inline-flex min-h-11 items-center rounded-lg border border-border-strong bg-surface px-5 py-2.5 font-medium text-fg hover:bg-surface-2">
          See a sample
        </Link>
      </div>
      {inviteOnly && (
        <div className="mt-4 text-sm text-muted">
          Have an invite code? <SignUpButton inviteOnly label="Sign up with your invite" variant="secondary" className="ml-1" />
        </div>
      )}
    </section>
  );
}

const STEPS = [
  { Icon: UploadIcon, title: "Add your resume and the job", body: "Upload a PDF or Word file and paste the job description. We split your resume into numbered bullets so every change can be traced." },
  { Icon: FileIcon, title: "Answer a few gap questions", body: "Requirements your resume doesn't show become yes-or-no questions for you. Nothing is filled in on your behalf." },
  { Icon: CheckIcon, title: "Review, score and download", body: "Accept or reject each rewritten line, see an ATS-style score with its full breakdown, and get mentor-style advice." },
];

function HowItWorks() {
  return (
    <Section id="how-it-works" title="How it works" intro="Three steps, usually a few minutes." tint>
      <ol className="grid gap-4 md:grid-cols-3">
        {STEPS.map(({ Icon, title, body }, i) => (
          <li key={title} className="rounded-2xl border border-border bg-bg p-5">
            <div className="flex items-center gap-3">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent-soft text-sm font-semibold text-accent" aria-hidden="true">{i + 1}</span>
              <Icon className="h-5 w-5 text-muted" />
            </div>
            <h3 className="mt-4 font-semibold">{title}</h3>
            <p className="mt-1.5 text-sm text-muted">{body}</p>
          </li>
        ))}
      </ol>
    </Section>
  );
}

const PROMISES = [
  { title: "Every line cites its source", body: "Each rewritten bullet names the original bullet it came from. No source, no rewrite." },
  { title: "A separate verifier checks the result", body: "It compares the tailored resume with your original and blocks new tools, numbers, titles, employers, and inflated verbs like “helped” becoming “led”." },
  { title: "You approve the diff", body: "You see before and after side by side and accept or reject each change. Nothing you didn't accept ends up in your file." },
];

function Honesty() {
  return (
    <Section id="honesty" title="The honesty guarantee"
      intro="Recruiters notice when a resume oversells, and so do interviewers. We only use what you've actually done.">
      <ul className="grid gap-4 md:grid-cols-3">
        {PROMISES.map(({ title, body }) => (
          <li key={title} className="rounded-2xl border border-border bg-surface p-5">
            <ShieldIcon className="h-5 w-5 text-accent" />
            <h3 className="mt-3 font-semibold">{title}</h3>
            <p className="mt-1.5 text-sm text-muted">{body}</p>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Sample() {
  return (
    <Section id="sample" tint title="A sample before and after"
      intro="Made-up example: a data analyst resume tailored to an analytics engineer job that asks for SQL, dashboards and dbt.">
      <div className="grid gap-4 lg:grid-cols-2">
        <SampleRow
          before="Worked on dashboards for the sales team using SQL and Tableau."
          after="Built SQL and Tableau dashboards for the sales team."
          source="Bullet 3"
          verdict={{ ok: true, text: "Passed: same tools, same scope, clearer wording" }}
        />
        <SampleRow
          before="Cleaned up monthly reporting so it took less time."
          after="Automated parts of monthly sales reporting, reducing manual effort."
          source="Bullet 5"
          verdict={{ ok: true, text: "Passed: mirrors the job's wording; no new number added" }}
        />
        <SampleRow
          before="Helped migrate reports to the new data warehouse."
          after="Led the migration of reports to the new data warehouse."
          source="Bullet 7"
          verdict={{ ok: false, text: "Blocked: “helped” can't become “led”" }}
        />
        <div className="rounded-2xl border border-border bg-bg p-5">
          <p className="text-sm font-medium text-muted">Gap question</p>
          <p className="mt-2 font-medium">The job asks for dbt. Have you used it?</p>
          <p className="mt-2 text-sm text-muted">
            Your resume doesn&apos;t mention dbt, so we ask instead of adding it. Say yes with a sentence of context and
            it can be used, citing your answer. Say no and the mentor suggests how to close the gap.
          </p>
        </div>
      </div>
      <p className="mt-4 text-sm text-muted">Demo data for illustration. Sample ATS-style score: 58 before, 74 after.</p>
    </Section>
  );
}

function SampleRow({ before, after, source, verdict }: {
  before: string;
  after: string;
  source: string;
  verdict: { ok: boolean; text: string };
}) {
  return (
    <div className="rounded-2xl border border-border bg-bg p-5">
      <dl className="space-y-3 text-sm">
        <div>
          <dt className="font-medium text-muted">Before</dt>
          <dd className="mt-1">{before}</dd>
        </div>
        <div>
          <dt className="font-medium text-muted">After <span className="font-normal">· cites {source}</span></dt>
          <dd className={`mt-1 ${verdict.ok ? "" : "text-muted line-through"}`}>{after}</dd>
        </div>
      </dl>
      <p className={`mt-3 inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-sm font-medium ${verdict.ok ? "bg-ok-bg text-ok" : "bg-bad-bg text-bad"}`}>
        {verdict.ok ? <CheckIcon /> : <ErrorIcon />} {verdict.text}
      </p>
    </div>
  );
}

function Pricing({ plans, inviteOnly }: { plans: Plans | null; inviteOnly: boolean }) {
  const paid = (plans?.plans ?? []).filter((p) => p.kind !== "subscription" || p.available);
  const start = inviteOnly
    ? { href: "/waitlist", label: "Request an invite" }
    : { href: "/signup", label: "Start free" };
  return (
    <Section id="pricing" title="Pricing"
      intro="Tailor and review for free. Pay only for the clean file you send to employers.">
      {plans ? (
        <ul className="grid items-stretch gap-x-4 gap-y-8 md:grid-cols-3 md:gap-y-4">
          <PriceCard name="Free" tagline="Try it on a real job" amount="₹0" detail="Every month"
            points={freePoints(plans.free_analyses_per_month)} cta={start} />
          {paid.map((p) => {
            const [main, ...other] = priceList(p.prices);
            return (
              <PriceCard key={p.key} name={p.name} featured={p.kind === "pass"}
                tagline={p.kind === "pass" ? "For an active job hunt" : p.kind === "credit_pack" ? "For a few applications" : "For ongoing use"}
                amount={main}
                detail={[other.length ? `or ${other.join(" / ")}` : "", p.kind === "subscription" ? `per ${p.interval}` : "one-time"]
                  .filter(Boolean).join(" · ")}
                points={planPoints(p, plans.redownload_free_days)}
                cta={{ href: "/pricing", label: p.kind === "pass" ? "Get the pass" : `Get the ${p.name.toLowerCase()}` }} />
            );
          })}
        </ul>
      ) : (
        <p className="max-w-2xl rounded-2xl border border-border bg-surface p-5">
          Every account gets free tailorings each month. Credit packs and the Job Hunt Pass pay for the clean
          downloads when you&apos;re applying to a lot of jobs.
        </p>
      )}
      <p className="mt-6 text-sm text-muted">
        {plans && (plans.prices_include_tax ? "Prices include taxes. " : "Taxes are added at checkout where they apply. ")}
        Payments are handled by Dodo Payments, our merchant of record.{" "}
        <Link href="/pricing" className="font-medium text-accent underline">Compare plans in detail</Link>
      </p>
    </Section>
  );
}

function PriceCard({ name, tagline, amount, detail, points, cta, featured = false }: {
  name: string;
  tagline: string;
  amount: string;
  detail: string;
  points: string[];
  cta: { href: string; label: string };
  featured?: boolean;
}) {
  const id = `plan-${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <li aria-labelledby={id} className={`relative flex flex-col rounded-2xl border bg-surface p-6 ${
      featured ? "border-accent ring-1 ring-accent" : "border-border"}`}>
      {featured && (
        <p className="absolute -top-3 left-6 rounded-full bg-accent px-3 py-0.5 text-xs font-semibold text-accent-fg">
          Best value
        </p>
      )}
      <h3 id={id} className="text-lg font-semibold">{name}</h3>
      <p className="mt-0.5 text-sm text-muted">{tagline}</p>
      <p className="mt-5 flex items-baseline gap-2">
        <span className="text-4xl font-semibold tracking-tight">{amount}</span>
      </p>
      <p className="mt-1 text-sm text-muted">{detail}</p>
      <ul className="mt-5 flex-1 space-y-2.5 border-t border-border pt-5 text-sm">
        {points.map((point) => (
          <li key={point} className="flex gap-2">
            <CheckIcon className="mt-0.5 h-4 w-4 shrink-0 text-ok" />
            <span>{point}</span>
          </li>
        ))}
      </ul>
      <Link href={cta.href} className={`mt-6 inline-flex min-h-11 items-center justify-center rounded-lg px-4 py-2 text-sm font-medium ${
        featured ? "bg-accent text-accent-fg hover:bg-accent-hover" : "border border-border-strong text-fg hover:bg-surface-2"}`}>
        {cta.label}
      </Link>
    </li>
  );
}

function Faq({ items }: { items: { q: string; a: string }[] }) {
  return (
    <Section id="faq" title="Questions" tint>
      <div className="max-w-3xl divide-y divide-border rounded-2xl border border-border bg-bg">
        {items.map(({ q, a }) => (
          <details key={q} className="group p-5">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium">
              {q}
              <span aria-hidden="true" className="text-muted transition-transform group-open:rotate-45">+</span>
            </summary>
            <p className="mt-3 text-sm text-muted">{a}</p>
          </details>
        ))}
      </div>
    </Section>
  );
}
