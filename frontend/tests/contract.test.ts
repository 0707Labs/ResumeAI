/**
 * Contract test: runs the real backend flow and validates every response against
 * our zod schemas. Needs the backend running; enable with CONTRACT=1.
 *   CONTRACT=1 npx vitest run tests/contract.test.ts
 */
// @vitest-environment node
import { describe, expect, it } from "vitest";

import { ApiError, api } from "@/lib/api";
import { authApi } from "@/lib/auth";

describe.runIf(process.env.CONTRACT === "1")("backend contract", () => {
  it("every endpoint matches the zod schemas", async () => {
    const sample = await api.sample();
    const resume = await api.parseResumeText(sample.resume_text);
    const jd = await api.parseJD(sample.jd_text);
    const analyzed = await api.analyze(resume, jd, false);
    const qids = analyzed.items.flatMap((i) => (i.question ? [i.question.id] : []));
    const analysis = await api.submitAnswers(analyzed, {
      [qids[0]]: { choice: "yes", text: "No formal course, but I ran t-tests on our A/B readouts." },
      [qids[1]]: { choice: "no", text: "" },
      [qids[2]]: { choice: "skip", text: "" },
    });
    expect(analysis.items.flatMap((i) => (i.question ? [i.question.answer_kind] : [])).slice(0, 3))
      .toEqual(["confirmed", "declined", "unanswered"]);
    const tailored = await api.tailor(resume, jd, analysis, false);
    const verified = await api.verify(resume, tailored.bullets, analysis, jd.raw_text, null);
    const score = await api.score(resume, jd, tailored, analysis, { approvedOnly: true });
    const mentor = await api.mentor(resume, jd, analysis, score.before, false);
    const preview = await api.exportPreview(resume, tailored, analysis, jd.raw_text);
    expect(preview.resume.name).toBe(resume.name);
    // Downloading needs sign-in (it's what pays); Node has no cookie jar, so we're signed out.
    const out = await api.exportFile("pdf", resume, jd, tailored, analysis).catch((e) => e);
    expect(resume.sections.length).toBeGreaterThan(0);
    expect(analysis.items.length).toBe(jd.requirements.length);
    expect(verified.bullets).toHaveLength(tailored.bullets.length);
    expect(score.after).not.toBeNull();
    expect(mentor.plan.weeks).toHaveLength(2);
    expect(out).toBeInstanceOf(ApiError);
    expect(out.kind).toBe("sign_in_required");
  }, 30_000);

  it("signed-out auth endpoints match the zod schemas", async () => {
    // Node has no cookie jar, so this is the view of a first-time visitor.
    expect(await api.me()).toBeNull();
    const providers = await authApi.providers();
    expect(providers.email).toBe(true);
    const notices = await authApi.notices(); // needs the database; empty until notices are published
    expect(Array.isArray(notices)).toBe(true);
    expect(await authApi.pending()).toBeNull();
  });
});
