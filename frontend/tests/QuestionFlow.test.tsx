import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AnalysisPage from "@/app/analysis/page";
import { GapCard } from "@/components/GapCard";
import { QuestionCard, isResolved, promptText } from "@/components/QuestionCard";
import { ApiError, api } from "@/lib/api";
import type { GapAnalysis, GapItem } from "@/lib/schemas";
import { useSession } from "@/lib/store";

import { jd, resume } from "./fixtures";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/analysis",
}));

const q = (id: string, req: string, text: string) => ({
  id, requirement_id: req, question: text, answer: null, answer_choice: null, answer_kind: "unanswered" as const,
});

const base = {
  priority: "required" as const, category: "skill" as const, evidence_entry_ids: [], evidence_skills: [],
  matched_keywords: [], missing_keywords: [], decided_by: "rules",
};

const items: GapItem[] = [
  { ...base, requirement_id: "req1", requirement_text: "Strong SQL", status: "evidenced",
    evidence_bullet_ids: ["exp1.b1"], matched_keywords: ["sql"], rationale: "SQL named in your bullets.", question: null },
  { ...base, requirement_id: "req2", requirement_text: "Statistics", status: "implied",
    evidence_bullet_ids: ["exp1.b1"], missing_keywords: ["statistics"], rationale: "Suggested by A/B testing.",
    question: q("q1", "req2", "The role asks for statistics. Did you use statistics directly? If not, just say no.") },
  { ...base, requirement_id: "req3", requirement_text: "Kubernetes in production", status: "missing",
    evidence_bullet_ids: [], missing_keywords: ["kubernetes"], rationale: "No mention of Kubernetes.",
    question: q("q2", "req3", "The role asks for Kubernetes. Have you used it, even in a side project? If not, just say no.") },
  { ...base, requirement_id: "req4", requirement_text: "Airflow", status: "missing", priority: "preferred",
    evidence_bullet_ids: [], missing_keywords: ["airflow"], rationale: "No mention of Airflow.",
    question: q("q3", "req4", "The role asks for Airflow. Have you used it? If not, just say no.") },
];

const analysis: GapAnalysis = {
  items, candidate_years_experience: 3, notes: ["Rules only."],
  counts: { evidenced: 1, implied: 1, missing: 2 }, required_coverage: 0.5,
};

beforeEach(() => {
  vi.restoreAllMocks();
  push.mockReset();
  useSession.getState().clearAll();
  useSession.getState().setResume(resume, { mode: "file", fileName: "cv.pdf" });
  useSession.getState().setAnalyzed(jd, analysis);
});

const question = (id: string) => screen.getByTestId(`question-${id}`);
const continueButton = () => screen.getByRole("button", { name: /continue to tailoring/i });

describe("GapCard", () => {
  it("shows status as icon + word, priority, and evidence bullet IDs", async () => {
    const user = userEvent.setup();
    render(<ul><GapCard item={items[0]} resume={resume} answer={undefined} onAnswer={vi.fn()} /></ul>);
    const card = screen.getByTestId("gap-req1");
    expect(within(card).getByText("Evidenced")).toBeInTheDocument();
    expect(within(card).getByText("Required")).toBeInTheDocument();
    expect(within(card).getByText("exp1.b1", { selector: "summary code" })).toBeInTheDocument();
    await user.click(within(card).getByText(/evidence:/i));
    expect(within(card).getByText(/cut weekly reporting time by 30%/i)).toBeVisible();
  });

  it("missing items always show a question; implied ones offer an optional one", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<ul><GapCard item={items[2]} resume={resume} answer={undefined} onAnswer={vi.fn()} /></ul>);
    expect(screen.getByTestId("question-q2")).toBeInTheDocument();

    rerender(<ul><GapCard item={items[1]} resume={resume} answer={undefined} onAnswer={vi.fn()} /></ul>);
    expect(screen.queryByTestId("question-q1")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /confirm this directly \(optional\)/i }));
    expect(screen.getByTestId("question-q1")).toBeInTheDocument();
  });
});

describe("QuestionCard", () => {
  it("drops the redundant 'If not, just say no' from the prompt", () => {
    expect(promptText(items[2].question!)).toBe("The role asks for Kubernetes. Have you used it, even in a side project?");
  });

  it("offers Yes / No / Skip and reveals a textarea for Yes", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(<QuestionCard question={items[2].question!} value={undefined} onChange={onChange} />);
    const group = screen.getByRole("radiogroup", { name: /your answer/i });
    expect(within(group).getAllByRole("radio").map((r) => (r as HTMLInputElement).value)).toEqual(["yes", "no", "skip"]);

    await user.click(screen.getByLabelText(/yes, i'll describe it/i));
    expect(onChange).toHaveBeenCalledWith({ choice: "yes", text: "" });

    rerender(<QuestionCard question={items[2].question!} value={{ choice: "yes", text: "" }} onChange={onChange} />);
    const box = screen.getByLabelText(/where and how did you use it/i);
    expect(box).toHaveAccessibleDescription(/a sentence about where and what you did/i);
  });

  it("radios are keyboard navigable", async () => {
    const user = userEvent.setup();
    let value: { choice: "yes" | "no" | "skip"; text: string } | undefined;
    const { rerender } = render(<QuestionCard question={items[2].question!} value={value} onChange={(v) => (value = v)} />);
    await user.tab();
    expect(screen.getByLabelText(/yes, i'll describe it/i)).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    rerender(<QuestionCard question={items[2].question!} value={value} onChange={(v) => (value = v)} />);
    expect(value?.choice).toBe("no");
  });

  it("isResolved needs a real description for Yes", () => {
    expect(isResolved(undefined)).toBe(false);
    expect(isResolved({ choice: "yes", text: "k8s" })).toBe(false);
    expect(isResolved({ choice: "yes", text: "Deployed a side-project API on minikube." })).toBe(true);
    expect(isResolved({ choice: "no", text: "" })).toBe(true);
    expect(isResolved({ choice: "skip", text: "" })).toBe(true);
  });
});

describe("Step 2: question flow", () => {
  it("groups requirements and counts each status", () => {
    render(<AnalysisPage />);
    expect(screen.getByRole("heading", { name: /already on your resume/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /hinted at, not stated/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /not on your resume yet/i })).toBeInTheDocument();
  });

  it("Continue stays disabled until every missing question is answered or skipped", async () => {
    const user = userEvent.setup();
    render(<AnalysisPage />);
    expect(continueButton()).toBeDisabled();
    expect(continueButton()).toHaveAccessibleDescription(/0 of 2 questions answered or skipped\. 2 to go/i);

    // Yes without a description doesn't count yet.
    await user.click(within(question("q2")).getByLabelText(/yes, i'll describe it/i));
    await user.click(within(question("q3")).getByLabelText(/^skip$/i));
    expect(continueButton()).toBeDisabled();

    await user.type(within(question("q2")).getByLabelText(/where and how/i), "Ran a side-project API on minikube.");
    expect(continueButton()).toBeEnabled();
  });

  it("the optional implied question never blocks", async () => {
    const user = userEvent.setup();
    render(<AnalysisPage />);
    await user.click(within(question("q2")).getByLabelText(/^no$/i));
    await user.click(within(question("q3")).getByLabelText(/^no$/i));
    expect(continueButton()).toBeEnabled();
  });

  it("sends explicit choices and moves to review", async () => {
    const user = userEvent.setup();
    const submit = vi.spyOn(api, "submitAnswers").mockImplementation(async (a) => a);
    render(<AnalysisPage />);

    await user.click(within(question("q2")).getByLabelText(/yes, i'll describe it/i));
    await user.type(within(question("q2")).getByLabelText(/where and how/i), "Ran a side-project API on minikube.");
    await user.click(within(question("q3")).getByLabelText(/^no$/i));
    // Optional implied question: opened, Yes chosen, but too short -> sent as skip.
    await user.click(screen.getByRole("button", { name: /confirm this directly/i }));
    await user.click(within(question("q1")).getByLabelText(/yes, i'll describe it/i));
    await user.type(within(question("q1")).getByLabelText(/where and how/i), "t-tests");

    await user.click(continueButton());
    await waitFor(() => expect(push).toHaveBeenCalledWith("/review"));
    expect(submit.mock.calls[0][1]).toEqual({
      q1: { choice: "skip", text: "" },
      q2: { choice: "yes", text: "Ran a side-project API on minikube." },
      q3: { choice: "no", text: "" },
    });
  });

  it("answers survive a reload (sessionStorage) and errors keep them", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "submitAnswers").mockRejectedValue(new ApiError("backend_down", 0));
    render(<AnalysisPage />);
    await user.click(within(question("q2")).getByLabelText(/^no$/i));
    await user.click(within(question("q3")).getByLabelText(/^skip$/i));
    await user.click(continueButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(/can't reach the analysis service/i);
    expect(push).not.toHaveBeenCalled();
    expect(JSON.parse(sessionStorage.getItem("resume-tailor-session")!).state.answers).toMatchObject({
      q2: { choice: "no" }, q3: { choice: "skip" },
    });
  });
});
