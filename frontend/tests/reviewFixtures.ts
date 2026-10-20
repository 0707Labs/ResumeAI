import type { ScoreResponse, TailoredBullet, TailoredResume } from "@/lib/schemas";

const ok = { flags: [], passed: true };

const bullet = (over: Partial<TailoredBullet>): TailoredBullet => ({
  id: "t0", text: "", source_bullet_ids: ["exp1.b1"], source_answer_ids: [], entry_id: "exp1",
  original_text: "", change_type: "reword", jd_terms_used: [], verification: ok,
  rejected_attempts: [], review: "pending", ...over,
});

export const verified = bullet({
  id: "t1", original_text: "Cut weekly reporting time by 30% with SQL",
  text: "Automated SQL reporting, cutting weekly reporting time by 30%", jd_terms_used: ["SQL"],
});

export const warned = bullet({
  id: "t2", source_bullet_ids: ["exp1.b2"], original_text: "Partnered with product managers on A/B test readouts",
  text: "Partnered with product managers and executives on A/B test readouts",
  verification: { passed: true, flags: [{ kind: "new_claim", token: "executive", detail: "These words don't trace to the source.", severity: "warn" }] },
});

export const blocked = bullet({
  id: "t3", source_bullet_ids: ["exp1.b3"], original_text: "Contributed to a churn dashboard in Tableau",
  text: "Led a churn dashboard in Tableau and Snowflake",
  verification: { passed: false, flags: [
    { kind: "inflated_verb", token: "Led", detail: "\"Led\" claims more than the source ('Contributed').", severity: "block" },
    { kind: "new_tool", token: "snowflake", detail: "\"snowflake\" isn't in the cited source.", severity: "block" },
  ] },
  rejected_attempts: [{ text: "Owned a churn dashboard", flags: [{ kind: "inflated_verb", token: "Owned", detail: "x", severity: "block" }] }],
});

export const unchanged = bullet({
  id: "t4", source_bullet_ids: ["exp1.b4"], original_text: "Built 12 recurring reports",
  text: "Built 12 recurring reports", change_type: "unchanged",
});

export const tailored: TailoredResume = {
  entry_order: ["exp1"], bullets: [verified, warned, blocked, unchanged], summary: null,
  summary_verification: null, summary_review: "pending", notes: ["Claude rewrote 3 bullet(s)."], blocked_rewrites: 1,
};

const report = (total: number) => ({ components: [], disclaimer: "Estimate only.", total });
export const scoreFor = (after: number): ScoreResponse => ({
  before: report(70), after: report(after), delta: Math.round((after - 70) * 10) / 10,
});
