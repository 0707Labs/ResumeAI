import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MentorPage from "@/app/app/mentor/page";
import { VERDICT, VerdictCard } from "@/components/MentorCard";
import { ApiError, api } from "@/lib/api";
import type { MentorAdvice } from "@/lib/schemas";
import { STORAGE_KEY, useSession } from "@/lib/store";

import { analysis, jd, resume } from "./fixtures";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/app/mentor",
}));

const advice: MentorAdvice = {
  strengths: [{ text: 'SQL: shown directly in "Cut weekly reporting time by 30% with SQL".', evidence_bullet_ids: ["exp1.b1"], requirement_ids: ["req1"] }],
  gaps: [
    { requirement_id: "req2", text: "Kubernetes", priority: "required", status: "missing", severity: "critical", why_it_matters: "It's listed as required." },
    { requirement_id: "req3", text: "dbt or Airflow", priority: "preferred", status: "missing", severity: "minor", why_it_matters: "Nice to have." },
  ],
  actions: [
    { id: "a1", kind: "answer_question", text: "Answer question q1 about Kubernetes.", effort: "5 min", requirement_ids: ["req2"], bullet_ids: [], question_id: "q1" },
    { id: "a2", kind: "learn", text: "Follow the 2-week plan for Kubernetes.", effort: "1-2 h/day", requirement_ids: ["req2"], bullet_ids: [], question_id: null },
  ],
  verdict: {
    decision: "stretch",
    headline: "Worth applying as a stretch.",
    reasons: ["You cover about 50% of the required items.", "Estimated ATS match: 61/100."],
    caveat: "This is guidance, not a prediction.",
  },
  plan: {
    focus_skills: ["kubernetes"], hours_per_day: "1-2 hours",
    weeks: [
      { week: 1, focus: "Fundamentals", tasks: [{ id: "w1t1", days: "Days 1-2", title: "Learn Kubernetes fundamentals", detail: "Kubernetes Basics tutorial.", deliverable: "A small exercise.", requirement_ids: ["req2"] }] },
      { week: 2, focus: "Proof", tasks: [{ id: "w2t1", days: "Days 6-8", title: "Build one small, real project", detail: "Keep it small.", deliverable: "A repo.", requirement_ids: [] }] },
    ],
    not_addressable: ["Years of experience: only time closes this."],
  },
  talking_points: [
    { id: "tp1", kind: "strength", prompt: 'Tell the story behind "Cut weekly reporting time by 30% with SQL"', detail: "Lead with the number.", bullet_ids: ["exp1.b1"], requirement_ids: ["req1"] },
    { id: "tp2", kind: "gap", prompt: "If they ask about Kubernetes", detail: "Say plainly that you haven't used it in a job yet.", bullet_ids: [], requirement_ids: ["req2"] },
  ],
  notes: ["Rules-based advice."],
};

beforeEach(() => {
  vi.restoreAllMocks();
  useSession.getState().clearAll();
  const s = useSession.getState();
  s.setResume(resume, { mode: "file", fileName: "cv.pdf" });
  s.setAnalyzed(jd, analysis);
});

describe("VerdictCard", () => {
  it.each([
    ["strong_fit", "Strong fit"],
    ["apply", "Worth a shot"],
    ["stretch", "Stretch"],
    ["not_yet", "Not yet"],
  ] as const)("%s reads as %s", (decision, label) => {
    expect(VERDICT[decision].label).toBe(label);
  });

  it("gives one paragraph of reasons", () => {
    render(<VerdictCard verdict={advice.verdict} />);
    const card = screen.getByTestId("verdict");
    expect(within(card).getByRole("heading", { name: /should you apply/i })).toBeInTheDocument();
    expect(within(card).getByText("Stretch")).toBeInTheDocument();
    const para = within(card).getByText(/worth applying as a stretch/i).closest("p")!;
    expect(para).toHaveTextContent("Worth applying as a stretch. You cover about 50% of the required items. Estimated ATS match: 61/100.");
  });
});

describe("Step 5: mentor page", () => {
  it("fetches advice using the original ATS report", async () => {
    const before = { components: [], disclaimer: "", total: 61 };
    useSession.getState().setScore({ before, after: null, delta: null });
    const mentor = vi.spyOn(api, "mentor").mockResolvedValue(advice);
    render(<MentorPage />);
    expect(await screen.findByTestId("verdict")).toBeInTheDocument();
    expect(mentor.mock.calls[0][3]).toEqual(before);
  });

  it("shows strengths first, then honest gaps, then the action plan", async () => {
    vi.spyOn(api, "mentor").mockResolvedValue(advice);
    render(<MentorPage />);
    await screen.findByTestId("verdict");
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    const order = ["What you bring", "Honest gaps", "Action plan"].map((t) => headings.indexOf(t));
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(order.every((i) => i >= 0)).toBe(true);

    const gaps = screen.getByRole("region", { name: /honest gaps/i });
    expect(within(gaps).getByText("Important")).toBeInTheDocument(); // severity as a word, not color
    expect(within(gaps).getByText("Minor")).toBeInTheDocument();
  });

  it("talking points are collapsed until opened", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "mentor").mockResolvedValue(advice);
    render(<MentorPage />);
    const tp = await screen.findByTestId("talking-points");
    expect(tp).not.toHaveAttribute("open");
    await user.click(within(tp).getByText(/interview talking points/i));
    expect(tp).toHaveAttribute("open");
    expect(within(tp).getByText("Stories to tell")).toBeVisible();
    expect(within(tp).getByText(/haven't used it in a job yet/)).toBeVisible();
  });

  it("the plan is a checklist whose ticks persist in the session", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "mentor").mockResolvedValue(advice);
    render(<MentorPage />);
    const plan = await screen.findByRole("region", { name: /two-week upskilling plan/i });
    expect(within(plan).getByText("0 of 2")).toBeInTheDocument();
    await user.click(within(plan).getByRole("checkbox", { name: /learn kubernetes fundamentals/i }));
    expect(within(plan).getByText("1 of 2")).toBeInTheDocument();
    expect(JSON.parse(sessionStorage.getItem(STORAGE_KEY)!).state.checked).toEqual({ "plan:w1t1": true });
    expect(within(plan).getByText(/things two weeks can't fix/i)).toBeInTheDocument();
  });

  it("actions are tickable and link to where you do them", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "mentor").mockResolvedValue(advice);
    render(<MentorPage />);
    const actions = await screen.findByRole("region", { name: /action plan/i });
    await user.click(within(actions).getByRole("checkbox", { name: /answer question q1/i }));
    expect(useSession.getState().checked["action:a1"]).toBe(true);
    expect(within(actions).getByRole("link", { name: /go to questions/i })).toHaveAttribute("href", "/app/analysis");
  });

  it("shows a friendly error with a retry", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "mentor").mockRejectedValueOnce(new ApiError("server", 500)).mockResolvedValue(advice);
    render(<MentorPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/something went wrong on our side/i);
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByTestId("verdict")).toBeInTheDocument();
  });
});
