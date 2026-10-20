/**
 * Contract test: runs the real backend flow and validates every response against
 * our zod schemas. Needs the backend running; enable with CONTRACT=1.
 *   CONTRACT=1 npx vitest run tests/contract.test.ts
 */
// @vitest-environment node
import { describe, expect, it } from "vitest";

import { api } from "@/lib/api";

describe.runIf(process.env.CONTRACT === "1")("backend contract", () => {
  it("every endpoint matches the zod schemas", async () => {
    const sample = await api.sample();
    const resume = await api.parseResumeText(sample.resume_text);
    const jd = await api.parseJD(sample.jd_text);
    const analysis = await api.analyze(resume, jd, false);
    const tailored = await api.tailor(resume, jd, analysis, false);
    const verified = await api.verify(resume, tailored.bullets, analysis, jd.raw_text, null);
    const score = await api.score(resume, jd, tailored, analysis, false);
    const mentor = await api.mentor(resume, jd, analysis, score.before, false);
    const out = await api.exportFile("pdf", resume, tailored, analysis, jd.raw_text);
    expect(resume.sections.length).toBeGreaterThan(0);
    expect(analysis.items.length).toBe(jd.requirements.length);
    expect(verified.bullets).toHaveLength(tailored.bullets.length);
    expect(score.after).not.toBeNull();
    expect(mentor.plan.weeks).toHaveLength(2);
    expect(out.filename).toMatch(/\.pdf$/);
  }, 30_000);
});
