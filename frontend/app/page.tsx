import type { Metadata } from "next";
import Link from "next/link";

import { ArrowRightIcon, CheckIcon, ErrorIcon, HelpIcon, ShieldIcon, UploadIcon } from "@/components/icons";
import { LandingView } from "@/components/site/LandingView";
import { PublicPage } from "@/components/site/PublicPage";
import { BeforeAfter, Seam } from "@/components/site/BeforeAfter";
import { freePoints, planPoints, priceList } from "@/lib/billing";
import { wordDiff } from "@/lib/diff";
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
      <LandingView />
      <script type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd(faq)).replace(/</g, "\\u003c") }} />
      <Hero inviteOnly={inviteOnly} />
      <HowItWorks />
      <Honesty />
      <Sample />
      <Pricing plans={plans} inviteOnly={inviteOnly} />
      <Faq items={faq} />
      <ClosingCta inviteOnly={inviteOnly} />
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

function Section({ id, eyebrow, title, intro, children, tint = false }: {
  id: string;
  eyebrow?: string;
  title: string;
  intro?: string;
  children: React.ReactNode;
  tint?: boolean;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className={`scroll-mt-16 ${tint ? "bg-surface" : ""}`}>
      <div className="mx-auto max-w-(--container) px-(--gutter) py-(--space-section)">
        <SectionHead id={id} eyebrow={eyebrow} title={title} intro={intro} />
        <div className="reveal mt-10 sm:mt-12">{children}</div>
      </div>
    </section>
  );
}

function SectionHead({ id, eyebrow, title, intro }: { id: string; eyebrow?: string; title: string; intro?: React.ReactNode }) {
  return (
    <div className="reveal max-w-(--measure)">
      {eyebrow && <p className="text-xs font-semibold uppercase tracking-[0.08em] text-accent">{eyebrow}</p>}
      <h2 id={`${id}-title`} className="mt-3 text-display font-semibold text-balance">{title}</h2>
      {intro && <p className="mt-4 text-lg text-muted">{intro}</p>}
    </div>
  );
}

const PRIMARY = "inline-flex min-h-12 items-center justify-center gap-2 rounded-card bg-accent px-6 py-3 font-medium text-accent-fg shadow-sm hover:bg-accent-hover";

function PrimaryCta({ inviteOnly }: { inviteOnly: boolean }) {
  return inviteOnly
    ? <Link href="/waitlist" className={PRIMARY}>Request an invite <ArrowRightIcon /></Link>
    : <Link href="/signup" className={PRIMARY}>Get started free <ArrowRightIcon /></Link>;
}

function Hero({ inviteOnly }: { inviteOnly: boolean }) {
  return (
    <section aria-labelledby="hero-title">
      <div className="mx-auto grid max-w-(--container) items-center gap-12 px-(--gutter) pb-16 pt-12 sm:pb-24 sm:pt-20 lg:grid-cols-[1fr_1.15fr] lg:gap-16">
        <div className="min-w-0">
          <p className="inline-flex items-center gap-1.5 text-sm font-medium text-accent">
            <ShieldIcon /> Never invents experience
          </p>
          <h1 id="hero-title" className="mt-4 text-hero font-semibold text-balance">
            Tailor your resume to any job, without ever inventing experience
          </h1>
          <p className="mt-6 max-w-xl text-lg text-muted">
            Upload your resume and paste the job description. We reorder and reword what&apos;s already true, ask
            about the gaps, and show you every change before it counts.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-4">
            <PrimaryCta inviteOnly={inviteOnly} />
            <Link href="#sample" className="inline-flex min-h-12 items-center gap-1.5 font-medium text-accent underline-offset-4 hover:underline">
              See a full sample <ArrowRightIcon />
            </Link>
          </div>
          <ul className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm text-muted">
            {["Every change cites your resume", "You approve each edit", "Free to try, no card"].map((t) => (
              <li key={t} className="flex items-center gap-1.5"><CheckIcon className="h-4 w-4 text-ok" />{t}</li>
            ))}
          </ul>
        </div>
        <BeforeAfter />
      </div>
    </section>
  );
}

const STEPS = [
  { Icon: UploadIcon, title: "Add your resume and the job", body: "Upload a PDF or Word file and paste the job description. We number every bullet so each change can be traced." },
  { Icon: HelpIcon, title: "Answer a few gap questions", body: "Requirements your resume doesn't show become quick yes-or-no questions. Nothing is filled in for you." },
  { Icon: CheckIcon, title: "Review, score and download", body: "Accept or reject each rewritten line, see an ATS-style score with its breakdown, and get mentor-style advice." },
];

/** Three steps joined by the seam: across from md up, down the left on phones. */
function HowItWorks() {
  return (
    <Section id="how-it-works" eyebrow="How it works" title="From job post to tailored resume in minutes" tint>
      <ol className="grid gap-10 md:grid-cols-3 md:gap-8">
        {STEPS.map(({ Icon, title, body }, i) => (
          <li key={title} className="relative pl-16 md:pl-0">
            {i < STEPS.length - 1 && (
              <span aria-hidden="true" className="absolute bottom-[-2.5rem] left-6 top-14 border-l-2 border-dashed border-seam/60 md:bottom-auto md:left-16 md:right-[-2rem] md:top-6 md:border-l-0 md:border-t-2" />
            )}
            <span className="absolute left-0 top-0 flex h-12 w-12 items-center justify-center rounded-card bg-accent-soft text-accent md:static">
              <Icon className="h-5 w-5" />
            </span>
            <p className="pt-1 text-xs font-semibold uppercase tracking-[0.08em] text-muted md:mt-5 md:pt-0">Step {i + 1}</p>
            <h3 className="mt-1 text-lg font-semibold">{title}</h3>
            <p className="mt-2 max-w-sm text-muted">{body}</p>
          </li>
        ))}
      </ol>
    </Section>
  );
}

const PROMISES = [
  { title: "Every line cites its source", body: "Each rewritten bullet names the original bullet it came from. No source, no rewrite." },
  { title: "A separate verifier checks the result", body: "It compares the tailored resume with your original, line by line, before you see it." },
  { title: "You approve the diff", body: "You accept or reject each change. Nothing you didn't accept ends up in your file." },
];

const BLOCKED = [
  "New tools or skills",
  "New numbers, including rounding and “doubled”",
  "New or self-given titles",
  "Other employers' work",
  "Stronger verbs or scope, like “helped” becoming “led”",
];
const ALLOWED = [
  "Reordering lines so the relevant ones come first",
  "Rewording for clarity",
  "Using the job's terms when the fact is already yours",
  "Bringing your existing numbers forward",
];

function Honesty() {
  return (
    <section id="honesty" aria-labelledby="honesty-title" className="scroll-mt-16">
      <div className="mx-auto grid max-w-(--container) gap-12 px-(--gutter) py-(--space-section) lg:grid-cols-[1fr_1.1fr] lg:gap-16">
        <div className="min-w-0">
          <SectionHead id="honesty" eyebrow="The verifier guarantee" title="Only what you've actually done"
            intro="Recruiters notice when a resume oversells, and so do interviewers. We make your real experience easier to see, and nothing more." />
          <ul className="reveal mt-10 space-y-6">
            {PROMISES.map(({ title, body }) => (
              <li key={title} className="flex gap-4">
                <ShieldIcon className="mt-1 h-5 w-5 text-accent" />
                <div>
                  <h3 className="font-semibold">{title}</h3>
                  <p className="mt-1 text-muted">{body}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div className="reveal min-w-0 self-start rounded-hero border border-border bg-surface">
          <p className="border-b border-border px-6 py-4 font-semibold">What the verifier checks</p>
          <div className="grid gap-6 p-6 sm:grid-cols-2">
            <div>
              <h3 className="flex items-center gap-1.5 text-sm font-semibold text-bad"><ErrorIcon />Blocked</h3>
              <ul className="mt-3 space-y-2.5 text-sm">
                {BLOCKED.map((t) => <li key={t} className="border-l-2 border-bad/40 pl-3">{t}</li>)}
              </ul>
            </div>
            <div>
              <h3 className="flex items-center gap-1.5 text-sm font-semibold text-ok"><CheckIcon />Allowed</h3>
              <ul className="mt-3 space-y-2.5 text-sm">
                {ALLOWED.map((t) => <li key={t} className="border-l-2 border-ok/40 pl-3">{t}</li>)}
              </ul>
            </div>
          </div>
          <blockquote className="border-t border-dashed border-seam px-6 py-5 font-medium text-fg">
            If it isn&apos;t in your resume or your own answers, it doesn&apos;t go in.
          </blockquote>
        </div>
      </div>
    </section>
  );
}

const SAMPLE = [
  { before: "Worked on dashboards for the sales team using SQL and Tableau.",
    after: "Built SQL and Tableau dashboards for the sales team.", source: "b3",
    verdict: { ok: true, text: "Passed: same tools, same scope, clearer wording" } },
  { before: "Rewrote slow report queries; refresh time went from 40 to 12 minutes.",
    after: "Cut report refresh time from 40 to 12 minutes by rewriting slow queries.", source: "b2",
    verdict: { ok: true, text: "Passed: same numbers, result moved first" } },
  { before: "Helped migrate reports to the new data warehouse.",
    after: "Led the migration of reports to the new data warehouse.", source: "b7",
    verdict: { ok: false, text: "Blocked: “helped” can't become “led”" } },
];

/** The sample diff: original, the seam with its source id, then the word diff and the verifier's word. */
function Sample() {
  return (
    <Section id="sample" tint eyebrow="See it in action" title="A sample before and after"
      intro="Made-up example: a data analyst resume tailored to an analytics engineer job that asks for SQL, dashboards and dbt.">
      <div className="overflow-hidden rounded-hero border border-border bg-bg">
        <div className="hidden grid-cols-[1fr_4.5rem_1fr] border-b border-border bg-surface-2 text-sm font-semibold text-muted sm:grid">
          <span className="px-6 py-3">Your resume</span><span /><span className="px-6 py-3">Tailored, with changes marked</span>
        </div>
        <ul className="divide-y divide-border">
          {SAMPLE.map(({ before, after, source, verdict }) => (
            <li key={source} className="grid p-5 sm:grid-cols-[1fr_4.5rem_1fr] sm:items-center sm:p-0">
              <p className="text-muted sm:px-6 sm:py-5">
                <span className="mb-1 block text-xs font-semibold sm:hidden">Your resume</span>
                <span className="sr-only">Before: </span>{before}
              </p>
              <Seam id={source} />
              <div className="sm:px-6 sm:py-5">
                <p className="mb-1 text-xs font-semibold text-muted sm:hidden">Tailored</p>
                <p className={verdict.ok ? "" : "opacity-70"}>
                  <span className="sr-only">After, citing {source}: </span>
                  {wordDiff(before, after).map((part, i) =>
                    part.type === "added" ? <ins key={i}>{part.text}</ins>
                      : part.type === "removed" ? <del key={i}>{part.text}</del>
                        : <span key={i}>{part.text}</span>)}
                </p>
                <p className={`mt-3 inline-flex items-start gap-1.5 rounded-md px-2 py-1 text-sm font-medium ${verdict.ok ? "bg-ok-bg text-ok" : "bg-bad-bg text-bad"}`}>
                  {verdict.ok ? <CheckIcon className="mt-0.5 h-4 w-4" /> : <ErrorIcon className="mt-0.5 h-4 w-4" />} {verdict.text}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </div>
      <p className="mt-3 text-sm text-muted">
        <del>Struck through</del> is removed, <ins>underlined</ins> is added. A blocked line never reaches your file.
      </p>
      <div className="mt-8 grid gap-4 md:grid-cols-2">
        <div className="rounded-card border border-border bg-bg p-6">
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-accent">Gap question</p>
          <p className="mt-2 text-lg font-medium">The job asks for dbt. Have you used it?</p>
          <p className="mt-2 text-muted">
            Your resume doesn&apos;t mention dbt, so we ask instead of adding it. Say yes with a sentence of context and
            it can be used, citing your answer. Say no and the mentor suggests how to close the gap.
          </p>
        </div>
        <div className="rounded-card border border-border bg-bg p-6">
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-accent">ATS-style score</p>
          <div className="mt-3 space-y-4">
            {[["Before", 58], ["After", 74]].map(([label, value]) => (
              <div key={label}>
                <div className="flex justify-between text-sm"><span className="text-muted">{label}</span><span className="font-semibold tabular-nums">{value}</span></div>
                <div className="mt-1.5 h-2.5 rounded-full bg-surface-2">
                  <div className={`h-full rounded-full ${label === "After" ? "bg-accent" : "bg-border-strong"}`} style={{ width: `${value}%` }} />
                </div>
              </div>
            ))}
          </div>
          <p className="mt-4 text-sm text-muted">Demo data. Real applicant tracking systems differ; we always show the breakdown.</p>
        </div>
      </div>
    </Section>
  );
}

function Pricing({ plans, inviteOnly }: { plans: Plans | null; inviteOnly: boolean }) {
  const paid = (plans?.plans ?? []).filter((p) => p.kind !== "subscription" || p.available);
  const start = inviteOnly
    ? { href: "/waitlist", label: "Request an invite" }
    : { href: "/signup", label: "Start free" };
  return (
    <Section id="pricing" eyebrow="Pricing" title="Simple, one-time prices"
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
        <p className="max-w-(--measure) rounded-card border border-border bg-surface p-5">
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
    <li aria-labelledby={id} className={`relative flex flex-col rounded-hero border bg-surface p-6 ${
      featured ? "border-accent ring-1 ring-accent" : "border-border"}`}>
      {featured && (
        <p className="absolute -top-3 left-6 rounded-full bg-accent px-3 py-0.5 text-xs font-semibold text-accent-fg">
          Best value
        </p>
      )}
      <h3 id={id} className="text-lg font-semibold">{name}</h3>
      <p className="mt-0.5 text-sm text-muted">{tagline}</p>
      <p className="mt-5 flex items-baseline gap-2">
        <span className="text-4xl font-semibold tracking-tight tabular-nums">{amount}</span>
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
      <Link href={cta.href} className={`mt-6 inline-flex min-h-11 items-center justify-center rounded-card px-4 py-2 text-sm font-medium ${
        featured ? "bg-accent text-accent-fg hover:bg-accent-hover" : "border border-border-strong text-fg hover:bg-surface-2"}`}>
        {cta.label}
      </Link>
    </li>
  );
}

function Faq({ items }: { items: { q: string; a: string }[] }) {
  return (
    <section id="faq" aria-labelledby="faq-title" className="scroll-mt-16 bg-surface">
      <div className="mx-auto grid max-w-(--container) gap-10 px-(--gutter) py-(--space-section) lg:grid-cols-[1fr_2fr] lg:gap-16">
        <SectionHead id="faq" eyebrow="Questions" title="Good to know" intro={
          <>Anything else? {COMPANY.supportEmail
            ? <>Write to <a href={`mailto:${COMPANY.supportEmail}`} className="font-medium text-accent underline">{COMPANY.supportEmail}</a>.</>
            : <>See <Link href="/legal/grievance" className="font-medium text-accent underline">how to reach us</Link>.</>}</>
        } />
        <div className="reveal min-w-0 divide-y divide-border border-y border-border">
          {items.map(({ q, a }) => (
            <details key={q} className="group py-5">
              <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 text-base font-medium [&::-webkit-details-marker]:hidden">
                {q}
                <span aria-hidden="true" className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border text-muted transition-transform group-open:rotate-45">+</span>
              </summary>
              <p className="mt-2 max-w-(--measure) text-muted">{a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

/** The navy band that closes the page. Its own colours (ink, ink-fg) work in both themes. */
function ClosingCta({ inviteOnly }: { inviteOnly: boolean }) {
  const cta = inviteOnly ? { href: "/waitlist", label: "Request an invite" } : { href: "/signup", label: "Get started free" };
  return (
    <section aria-labelledby="cta-title" className="bg-ink text-ink-fg">
      <div className="mx-auto max-w-(--container) px-(--gutter) py-(--space-section)">
        <div className="reveal max-w-2xl">
          <h2 id="cta-title" className="text-display font-semibold text-balance">
            Your real experience, framed for the job you want
          </h2>
          <p className="mt-4 text-lg opacity-80">
            Tailoring and review are free to try. Pay only for the clean file you send.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-4">
            <Link href={cta.href} className="inline-flex min-h-12 items-center gap-2 rounded-card bg-ink-fg px-6 py-3 font-medium text-ink hover:opacity-90">
              {cta.label} <ArrowRightIcon />
            </Link>
            <Link href="#pricing" className="inline-flex min-h-12 items-center font-medium underline underline-offset-4 hover:opacity-80">
              See pricing
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
