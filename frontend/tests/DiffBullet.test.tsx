import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ReviewPage from "@/app/app/review/page";
import { DiffBullet } from "@/components/DiffBullet";
import { api } from "@/lib/api";
import { approveAllVerified, decide, exportCheck, withDecisions } from "@/lib/review";
import type { TailoredResume } from "@/lib/schemas";
import { useSession } from "@/lib/store";

import { analysis, jd, resume } from "./fixtures";
import { blocked, scoreFor, tailored, unchanged, verified, warned } from "./reviewFixtures";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/app/review",
}));

// --- review rules ----------------------------------------------------------------------------

describe("export gating", () => {
  it("flagged changes block export until explicitly resolved", () => {
    let d = {};
    expect(exportCheck(tailored, d)).toMatchObject({ ok: false, unresolved: ["t2", "t3"] });

    d = decide(d, warned, "approved"); // a warning can be approved on purpose
    d = decide(d, blocked, "rejected"); // a blocked one can be kept original
    expect(exportCheck(tailored, d).ok).toBe(true);
  });

  it("a blocked change can never be approved", () => {
    const d = decide({}, blocked, "approved");
    expect(d).toEqual({});
    // Even a forged decision doesn't count as resolved.
    expect(exportCheck(tailored, { t2: "rejected", t3: "approved" })).toMatchObject({ ok: false, unresolved: ["t3"] });
  });

  it("verified and unchanged lines never block export", () => {
    const only: TailoredResume = { ...tailored, bullets: [verified, unchanged] };
    expect(exportCheck(only, {}).ok).toBe(true);
  });

  it("a flagged summary must be decided too", () => {
    const withSummary: TailoredResume = {
      ...tailored, bullets: [verified], summary: "Senior analyst.",
      summary_verification: { passed: false, flags: [{ kind: "new_title", token: "Senior", detail: "x", severity: "block" }] },
    };
    expect(exportCheck(withSummary, {}).summaryUnresolved).toBe(true);
    expect(exportCheck({ ...withSummary, summary_review: "rejected" }, {}).ok).toBe(true);
  });

  it("Approve all verified never approves a flagged change", () => {
    const d = approveAllVerified(tailored, {});
    expect(d).toEqual({ t1: "approved" });
  });

  it("decisions are sent as review fields; unchanged stay pending", () => {
    const out = withDecisions(tailored, { t1: "approved", t3: "rejected", t4: "approved" });
    expect(out.bullets.map((b) => b.review)).toEqual(["approved", "pending", "rejected", "pending"]);
  });
});

// --- DiffBullet component -----------------------------------------------------------------------------

describe("DiffBullet", () => {
  const props = { answers: [], onDecide: vi.fn(), onEdit: vi.fn(async () => {}) };

  it("verified: shows original vs tailored with word-level marks and the why note", () => {
    render(<ul><DiffBullet bullet={verified} decision="pending" {...props} /></ul>);
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.getByText(/from/i)).toHaveTextContent("exp1.b1");
    const tailoredSide = screen.getByTestId("tailored");
    expect(within(tailoredSide).getAllByText(/added:/).length).toBeGreaterThan(0);
    expect(tailoredSide.querySelector("ins")).toHaveTextContent(/Automated/);
    expect(screen.getByTestId("original").querySelector("del")).not.toBeNull();
    expect(screen.getByText(/why this change:/i).parentElement).toHaveTextContent(/Job wording used: SQL/);
  });

  it("blocked: names exactly what's new and can't be approved", async () => {
    const onDecide = vi.fn();
    render(<ul><DiffBullet bullet={blocked} decision="pending" {...props} onDecide={onDecide} /></ul>);
    expect(screen.getByText("Needs your check")).toBeInTheDocument();
    const found = screen.getByRole("list", { name: /what the verifier found/i });
    expect(within(found).getByText("Led")).toBeInTheDocument();
    expect(within(found).getByText("snowflake")).toBeInTheDocument();
    expect(within(found).getByText(/blocked: new tool or skill/i)).toBeInTheDocument();

    const approve = screen.getByRole("button", { name: /^approve$/i });
    expect(approve).toBeDisabled();
    expect(approve).toHaveAccessibleDescription(/says something your resume doesn't/i);

    await userEvent.click(screen.getByRole("button", { name: /reject \(keep original\)/i }));
    expect(onDecide).toHaveBeenCalledWith("rejected");
    expect(screen.getByText(/refused 1 earlier rewrite/i)).toBeInTheDocument();
  });

  it("warning-only: needs a check but can be approved deliberately", async () => {
    const onDecide = vi.fn();
    render(<ul><DiffBullet bullet={warned} decision="pending" {...props} onDecide={onDecide} /></ul>);
    expect(screen.getByText("Needs your check")).toBeInTheDocument();
    expect(screen.getByText(/check: wording to check/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    expect(onDecide).toHaveBeenCalledWith("approved");
  });

  it("edit manually sends the new text and cited answers for re-checking", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn(async () => {});
    const answers = [{ id: "q2", requirement: "Airflow", answer: "I wrote Airflow DAGs at Acme." }];
    render(<ul><DiffBullet bullet={blocked} decision="pending" {...props} answers={answers} onEdit={onEdit} /></ul>);
    await user.click(screen.getByRole("button", { name: /edit manually/i }));
    const box = screen.getByLabelText(/your wording/i);
    await user.clear(box);
    await user.type(box, "Contributed to a churn dashboard in Tableau, scheduled with Airflow");
    await user.click(screen.getByLabelText(/q2/));
    await user.click(screen.getByRole("button", { name: /save and re-check/i }));
    expect(onEdit).toHaveBeenCalledWith("Contributed to a churn dashboard in Tableau, scheduled with Airflow", ["q2"]);
  });
});

// --- review page ----------------------------------------------------------------------------------

describe("Step 3: review page", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useSession.getState().clearAll();
    const s = useSession.getState();
    s.setResume(resume, { mode: "file", fileName: "cv.pdf" });
    s.setAnalyzed(jd, analysis);
  });

  it("drafts on first visit, then updates the live score as decisions change", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "tailor").mockResolvedValue(tailored);
    const score = vi.spyOn(api, "score").mockImplementation(async (_r, _j, t) =>
      scoreFor(70 + 2 * (t?.bullets.filter((b) => b.review === "approved").length ?? 0)));

    render(<ReviewPage />);
    expect(await screen.findByRole("heading", { name: /review each change/i })).toBeInTheDocument();
    const bar = screen.getByTestId("review-bar");
    expect(within(bar).getByText(/2 flagged changes need your decision before export/i)).toBeInTheDocument();
    await waitFor(() => expect(within(bar).getByTestId("live-score")).toHaveTextContent(/70\.0.*70\.0/));

    // Bulk approve takes only the verified one.
    await user.click(within(bar).getByRole("button", { name: /approve all verified \(1\)/i }));
    expect(useSession.getState().decisions).toEqual({ t1: "approved" });
    await waitFor(() => expect(within(bar).getByTestId("live-score")).toHaveTextContent(/72\.0\s*\+2\.0/));
    const lastCall = score.mock.calls.at(-1)!;
    expect(lastCall[4]).toMatchObject({ approvedOnly: true });

    // Resolve the flagged ones explicitly.
    await user.click(within(screen.getByTestId("bullet-t2")).getByRole("button", { name: /^approve$/i }));
    await user.click(within(screen.getByTestId("bullet-t3")).getByRole("button", { name: /reject/i }));
    expect(within(bar).getByText(/ready to export/i)).toBeInTheDocument();
    await waitFor(() => expect(within(bar).getByTestId("live-score")).toHaveTextContent(/74\.0/));
  });

  it("a manual edit is re-verified and its decision resets", async () => {
    const user = userEvent.setup();
    useSession.getState().setTailored(tailored);
    vi.spyOn(api, "score").mockResolvedValue(scoreFor(70));
    const fixed = { ...blocked, text: "Contributed to a churn dashboard in Tableau for the success team", verification: { flags: [], passed: true } };
    const verify = vi.spyOn(api, "verify").mockResolvedValue({ bullets: [fixed], summary_verification: null });

    render(<ReviewPage />);
    const card = screen.getByTestId("bullet-t3");
    await user.click(within(card).getByRole("button", { name: /edit manually/i }));
    const box = within(card).getByLabelText(/your wording/i);
    await user.clear(box);
    await user.type(box, fixed.text);
    await user.click(within(card).getByRole("button", { name: /save and re-check/i }));

    await waitFor(() => expect(within(screen.getByTestId("bullet-t3")).getByText("Verified")).toBeInTheDocument());
    expect(verify.mock.calls[0][1][0]).toMatchObject({ id: "t3", text: fixed.text });
    expect(within(screen.getByTestId("bullet-t3")).getByText(/edited by you/i)).toBeInTheDocument();
    expect(within(screen.getByTestId("bullet-t3")).getByRole("button", { name: /^approve$/i })).toBeEnabled();
  });

  it("asks for the open questions first if they were skipped over", () => {
    const withQuestion = {
      ...analysis,
      items: [{ ...analysis.items[0], status: "missing" as const, evidence_bullet_ids: [],
        question: { id: "q1", requirement_id: "req1", question: "Have you used SQL?", answer: null, answer_choice: null, answer_kind: "unanswered" as const } }],
    };
    useSession.getState().setAnalyzed(jd, withQuestion);
    const tailor = vi.spyOn(api, "tailor");
    render(<ReviewPage />);
    expect(screen.getByText(/a couple of questions first/i)).toBeInTheDocument();
    expect(tailor).not.toHaveBeenCalled();
  });
});

describe("wordDiff", () => {
  it("treats a word at the end of a line the same as mid-line", async () => {
    const { wordDiff } = await import("@/lib/diff");
    const parts = wordDiff("automating SQL extracts", "automating SQL extracts as Airflow DAGs");
    expect(parts).toEqual([
      { type: "same", text: "automating SQL extracts " },
      { type: "added", text: "as Airflow DAGs" },
    ]);
  });
});
