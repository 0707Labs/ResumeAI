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
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
        <div className="max-w-2xl">
          {eyebrow && <p className="text-sm font-semibold tracking-wide text-accent">{eyebrow}</p>}
          <h2 id={`${id}-title`} className="mt-2 text-3xl font-semibold tracking-tight text-balance sm:text-4xl">{title}</h2>
          {intro && <p className="mt-4 text-lg text-muted">{intro}</p>}
        </div>
        <div className="mt-10 sm:mt-12">{children}</div>
      </div>
    </section>
  );
}

const PRIMARY = "inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-accent px-6 py-3 font-medium text-accent-fg shadow-sm hover:bg-accent-hover";
const SECONDARY = "inline-flex min-h-12 items-center justify-center rounded-xl border border-border-strong bg-surface px-6 py-3 font-medium text-fg hover:bg-surface-2";

function PrimaryCta({ inviteOnly }: { inviteOnly: boolean }) {
  return inviteOnly
    ? <Link href="/waitlist" className={PRIMARY}>Request an invite <ArrowRightIcon /></Link>
    : <Link href="/signup" className={PRIMARY}>Get started free <ArrowRightIcon /></Link>;
}

function Hero({ inviteOnly }: { inviteOnly: boolean }) {
  return (
    <section aria-labelledby="hero-title" className="relative overflow-hidden">
      <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-0 h-[32rem] bg-gradient-to-b from-accent-soft/70 to-transparent" />
      <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-4 pb-16 pt-14 sm:px-6 sm:pb-24 sm:pt-20 lg:grid-cols-[1.05fr_1fr] lg:gap-14">
        <div>
          <p className="inline-flex items-center gap-1.5 rounded-full border border-accent/20 bg-surface px-3 py-1 text-sm font-medium text-accent">
            <ShieldIcon /> Honest by design
          </p>
          <h1 id="hero-title" className="mt-6 text-4xl font-semibold leading-[1.08] tracking-tight text-balance sm:text-5xl lg:text-[3.4rem]">
            Tailor your resume to any job, without ever inventing experience
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted">
            Upload your resume and paste the job description. We reorder and reword what&apos;s already true, ask
            about the gaps, and show you every change before it counts.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <PrimaryCta inviteOnly={inviteOnly} />
            <Link href="#sample" className={SECONDARY}>See a sample</Link>
          </div>
          {inviteOnly && (
            <div className="mt-4 flex flex-wrap items-center gap-2 text-sm text-muted">
              Have an invite code? <SignUpButton inviteOnly label="Sign up with your invite" variant="secondary" />
            </div>
          )}
          <ul className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm text-muted">
            {["Every change cites your resume", "You approve each edit", "Free to try, no card"].map((t) => (
              <li key={t} className="flex items-center gap-1.5"><CheckIcon className="h-4 w-4 text-ok" />{t}</li>
            ))}
          </ul>
        </div>
        <HeroPreview />
      </div>
    </section>
  );
}

/** A still picture of the review screen, drawn with HTML (made-up data). */
function HeroPreview() {
  return (
    <figure role="img" aria-label="Example of the review screen: a reworded bullet that passed the verifier, a stronger claim that was blocked, and the ATS-style score rising from 58 to 74."
      className="relative mx-auto w-full max-w-xl">
      <div aria-hidden="true" className="absolute -inset-4 -z-10 rounded-[2rem] bg-accent-soft/60 blur-2xl" />
      <div aria-hidden="true" className="overflow-hidden rounded-2xl border border-border bg-surface shadow-xl">
        <div className="flex items-center gap-2 border-b border-border bg-surface-2 px-4 py-3">
          <span className="h-2.5 w-2.5 rounded-full bg-border-strong" />
          <span className="h-2.5 w-2.5 rounded-full bg-border-strong" />
          <span className="h-2.5 w-2.5 rounded-full bg-border-strong" />
          <span className="ml-3 truncate text-xs font-medium text-muted">Review · Data Analyst → Analytics Engineer</span>
        </div>
        <div className="space-y-3 p-4 sm:p-5">
          <div className="rounded-xl border border-border p-4">
            <p className="text-xs font-medium text-muted">Before</p>
            <p className="mt-1 text-sm text-muted">Worked on dashboards for the sales team using SQL and Tableau.</p>
            <p className="mt-3 text-xs font-medium text-muted">After <span className="rounded bg-surface-2 px-1.5 py-0.5 font-mono">cites b3</span></p>
            <p className="mt-1 text-sm font-medium">Built SQL and Tableau dashboards for the sales team.</p>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1 rounded-md bg-ok-bg px-2 py-0.5 text-xs font-medium text-ok"><CheckIcon className="h-3.5 w-3.5" />Verified</span>
              <span className="inline-flex items-center gap-1 rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-accent-fg"><CheckIcon className="h-3.5 w-3.5" />Approved</span>
            </div>
          </div>
          <div className="rounded-xl border border-bad/30 bg-bad-bg/40 p-4">
            <p className="text-sm text-muted line-through">Led the migration of reports to the new warehouse.</p>
            <span className="mt-2 inline-flex items-center gap-1 rounded-md bg-bad-bg px-2 py-0.5 text-xs font-medium text-bad"><ErrorIcon className="h-3.5 w-3.5" />Blocked: “helped” can&apos;t become “led”</span>
          </div>
          <div className="rounded-xl border border-border p-4">
            <div className="flex items-baseline justify-between text-sm">
              <span className="font-medium">ATS-style score</span>
              <span className="text-muted">58 → <span className="text-lg font-semibold text-fg">74</span></span>
            </div>
            <div className="relative mt-3 h-2 rounded-full bg-surface-2">
              <div className="absolute inset-y-0 left-0 w-[74%] rounded-full bg-accent/30" />
              <div className="absolute inset-y-0 left-0 w-[58%] rounded-full bg-accent" />
            </div>
          </div>
        </div>
      </div>
    </figure>
  );
}

const STEPS = [
  { Icon: UploadIcon, title: "Add your resume and the job", body: "Upload a PDF or Word file and paste the job description. We number every bullet so each change can be traced." },
  { Icon: FileIcon, title: "Answer a few gap questions", body: "Requirements your resume doesn't show become quick yes-or-no questions. Nothing is filled in for you." },
  { Icon: CheckIcon, title: "Review, score and download", body: "Accept or reject each rewritten line, see an ATS-style score with its breakdown, and get mentor-style advice." },
];

function HowItWorks() {
  return (
    <Section id="how-it-works" eyebrow="How it works" title="From job post to tailored resume in minutes" tint>
      <ol className="relative grid gap-10 md:grid-cols-3 md:gap-8">
        <div aria-hidden="true" className="absolute left-[16%] right-[16%] top-6 hidden border-t-2 border-dashed border-border md:block" />
        {STEPS.map(({ Icon, title, body }, i) => (
          <li key={title} className="relative flex flex-col items-start md:items-center md:text-center">
            <span className="relative flex h-12 w-12 items-center justify-center rounded-2xl bg-accent text-accent-fg shadow-sm">
              <Icon className="h-5 w-5" />
            </span>
            <p className="mt-5 text-sm font-semibold text-accent">Step {i + 1}</p>
            <h3 className="mt-1 text-lg font-semibold">{title}</h3>
            <p className="mt-2 max-w-xs leading-relaxed text-muted">{body}</p>
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
    <section id="honesty" aria-labelledby="honesty-title" className="scroll-mt-16">
      <div className="mx-auto grid max-w-6xl gap-12 px-4 py-16 sm:px-6 sm:py-24 lg:grid-cols-[1fr_1.2fr] lg:gap-16">
        <div>
          <p className="text-sm font-semibold tracking-wide text-accent">The honesty guarantee</p>
          <h2 id="honesty-title" className="mt-2 text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
            Only what you&apos;ve actually done
          </h2>
          <p className="mt-4 text-lg text-muted">
            Recruiters notice when a resume oversells, and so do interviewers. We make your real experience easier to
            see, and nothing more.
          </p>
          <blockquote className="mt-8 border-l-4 border-accent pl-5 text-lg font-medium text-fg">
            If it isn&apos;t in your resume or your own answers, it doesn&apos;t go in.
          </blockquote>
        </div>
        <ul className="space-y-4">
          {PROMISES.map(({ title, body }, i) => (
            <li key={title} className="flex gap-4 rounded-2xl border border-border bg-surface p-6">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent">
                <ShieldIcon className="h-5 w-5" />
              </span>
              <div>
                <h3 className="font-semibold"><span className="sr-only">{i + 1}. </span>{title}</h3>
                <p className="mt-1.5 leading-relaxed text-muted">{body}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

const SAMPLE = [
  { before: "Worked on dashboards for the sales team using SQL and Tableau.",
    after: "Built SQL and Tableau dashboards for the sales team.", source: "b3",
    verdict: { ok: true, text: "Passed: same tools, same scope, clearer wording" } },
  { before: "Cleaned up monthly reporting so it took less time.",
    after: "Automated parts of monthly sales reporting, reducing manual effort.", source: "b5",
    verdict: { ok: true, text: "Passed: mirrors the job's wording, no new number" } },
  { before: "Helped migrate reports to the new data warehouse.",
    after: "Led the migration of reports to the new data warehouse.", source: "b7",
    verdict: { ok: false, text: "Blocked: “helped” can't become “led”" } },
];

function Sample() {
  return (
    <Section id="sample" tint eyebrow="See it in action" title="A sample before and after"
      intro="Made-up example: a data analyst resume tailored to an analytics engineer job that asks for SQL, dashboards and dbt.">
      <div className="overflow-hidden rounded-2xl border border-border bg-bg">
        <div className="hidden grid-cols-[1fr_1fr_15rem] gap-6 border-b border-border bg-surface-2 px-6 py-3 text-sm font-semibold text-muted md:grid">
          <span>Your resume</span><span>Tailored</span><span>Verifier</span>
        </div>
        <ul className="divide-y divide-border">
          {SAMPLE.map(({ before, after, source, verdict }) => (
            <li key={source} className="grid gap-3 px-6 py-5 md:grid-cols-[1fr_1fr_15rem] md:gap-6">
              <div>
                <p className="text-xs font-semibold text-muted md:hidden">Your resume</p>
                <p className="leading-relaxed text-muted">{before}</p>
              </div>
              <div>
                <p className="text-xs font-semibold text-muted md:hidden">Tailored</p>
                <p className={`leading-relaxed ${verdict.ok ? "font-medium" : "text-muted line-through"}`}>{after}</p>
                <p className="mt-1 text-xs text-muted">cites <span className="font-mono">{source}</span></p>
              </div>
              <div>
                <p className={`inline-flex items-start gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium ${verdict.ok ? "bg-ok-bg text-ok" : "bg-bad-bg text-bad"}`}>
                  {verdict.ok ? <CheckIcon className="mt-0.5 h-4 w-4" /> : <ErrorIcon className="mt-0.5 h-4 w-4" />} {verdict.text}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div className="rounded-2xl border border-border bg-bg p-6">
          <p className="text-sm font-semibold text-accent">Gap question</p>
          <p className="mt-2 text-lg font-medium">The job asks for dbt. Have you used it?</p>
          <p className="mt-2 leading-relaxed text-muted">
            Your resume doesn&apos;t mention dbt, so we ask instead of adding it. Say yes with a sentence of context and
            it can be used, citing your answer. Say no and the mentor suggests how to close the gap.
          </p>
        </div>
        <div className="rounded-2xl border border-border bg-bg p-6">
          <p className="text-sm font-semibold text-accent">ATS-style score</p>
          <div className="mt-3 space-y-4">
            {[["Before", 58], ["After", 74]].map(([label, value]) => (
              <div key={label}>
                <div className="flex justify-between text-sm"><span className="text-muted">{label}</span><span className="font-semibold">{value}</span></div>
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
    <section id="faq" aria-labelledby="faq-title" className="scroll-mt-16 bg-surface">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 sm:py-24 lg:grid-cols-[1fr_2fr] lg:gap-16">
        <div>
          <p className="text-sm font-semibold tracking-wide text-accent">Questions</p>
          <h2 id="faq-title" className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Good to know</h2>
          <p className="mt-4 text-lg text-muted">
            Anything else? {COMPANY.supportEmail
              ? <>Write to <a href={`mailto:${COMPANY.supportEmail}`} className="font-medium text-accent underline">{COMPANY.supportEmail}</a>.</>
              : <>See <Link href="/legal/grievance" className="font-medium text-accent underline">how to reach us</Link>.</>}
          </p>
        </div>
        <div className="divide-y divide-border rounded-2xl border border-border bg-bg">
          {items.map(({ q, a }) => (
            <details key={q} className="group px-6 py-5">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-base font-medium [&::-webkit-details-marker]:hidden">
                {q}
                <span aria-hidden="true" className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border text-muted transition-transform group-open:rotate-45">+</span>
              </summary>
              <p className="mt-3 leading-relaxed text-muted">{a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

function ClosingCta({ inviteOnly }: { inviteOnly: boolean }) {
  return (
    <section aria-labelledby="cta-title" className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
      <div className="rounded-3xl bg-accent px-6 py-12 text-center text-accent-fg sm:px-12 sm:py-16">
        <h2 id="cta-title" className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
          Your real experience, framed for the job you want
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-lg opacity-90">
          Tailoring and review are free to try. Pay only for the clean file you send.
        </p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          {inviteOnly ? (
            <Link href="/waitlist" className="inline-flex min-h-12 items-center gap-2 rounded-xl bg-surface px-6 py-3 font-medium text-fg hover:bg-surface-2">
              Request an invite <ArrowRightIcon />
            </Link>
          ) : (
            <Link href="/signup" className="inline-flex min-h-12 items-center gap-2 rounded-xl bg-surface px-6 py-3 font-medium text-fg hover:bg-surface-2">
              Get started free <ArrowRightIcon />
            </Link>
          )}
          <Link href="#pricing" className="inline-flex min-h-12 items-center rounded-xl border border-current/30 px-6 py-3 font-medium hover:bg-white/10">
            See pricing
          </Link>
        </div>
      </div>
    </section>
  );
}
