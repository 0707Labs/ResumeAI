import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ScorePage from "@/app/app/score/page";
import { BreakdownBars } from "@/components/BreakdownBars";
import { KeywordChips } from "@/components/KeywordChips";
import { ScoreRing, clampScore } from "@/components/ScoreRing";
import { api } from "@/lib/api";
import type { ATSReport, ScoreComponent, ScoreResponse } from "@/lib/schemas";
import { useSession } from "@/lib/store";

import { analysis, jd, resume } from "./fixtures";
import { tailored } from "./reviewFixtures";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/app/score",
}));

const WEIGHTS = {
  required_keywords: 0.4, preferred_keywords: 0.1, semantic_relevance: 0.2,
  title_seniority: 0.1, format_parseability: 0.1, quantified_impact: 0.1,
} as const;

function report(scores: Partial<Record<keyof typeof WEIGHTS, number>>, extra: Partial<Record<string, Partial<ScoreComponent>>> = {}): ATSReport {
  const components = (Object.keys(WEIGHTS) as (keyof typeof WEIGHTS)[]).map((name) => {
    const score = scores[name] ?? 1;
    return {
      name, score, weight: WEIGHTS[name], points: Math.round(score * WEIGHTS[name] * 1000) / 10,
      deterministic: true, matched: [], missing: [], notes: "", ...extra[name],
    } as ScoreComponent;
  });
  const total = Math.round(components.reduce((s, c) => s + c.points, 0) * 10) / 10;
  return { components, total, disclaimer: "This is an estimate. Real ATS systems parse and rank differently." };
}

const before = report({ required_keywords: 0.75, preferred_keywords: 0 }, {
  required_keywords: { matched: ["sql", "python", "tableau"], missing: ["statistics"], notes: "statistics is implied by a/b testing." },
  preferred_keywords: { matched: [], missing: ["dbt / airflow", "snowflake / bigquery"] },
});
const after = report({ required_keywords: 0.75, preferred_keywords: 0.5 }, {
  required_keywords: { matched: ["sql", "python", "tableau"], missing: ["statistics"] },
  preferred_keywords: { matched: ["dbt / airflow"], missing: ["snowflake / bigquery"] },
});
const response: ScoreResponse = { before, after, delta: Math.round((after.total - before.total) * 10) / 10 };

describe("ScoreRing", () => {
  it("announces the value as text and clamps it", () => {
    render(<ScoreRing value={75.8} label="With your changes" />);
    expect(screen.getByRole("img", { name: "With your changes: 75.8 out of 100" })).toBeInTheDocument();
    expect(clampScore(140)).toBe(100);
    expect(clampScore(-3)).toBe(0);
  });

  it("animates the arc toward the value", async () => {
    render(<ScoreRing value={50} label="x" />);
    const arc = screen.getByTestId("ring-arc");
    const full = Number(arc.getAttribute("stroke-dasharray"));
    await waitFor(() => expect(Number(arc.getAttribute("stroke-dashoffset"))).toBeCloseTo(full / 2, 1));
  });
});

describe("BreakdownBars", () => {
  it("lists all six components with their weights, in order", () => {
    render(<BreakdownBars before={before} after={null} />);
    const items = within(screen.getByRole("list", { name: /score breakdown/i })).getAllByRole("listitem")
      .filter((li) => li.dataset.testid?.startsWith("component-"));
    expect(items.map((li) => li.querySelector("p")!.textContent)).toEqual([
      "Required keywords · weight 40%",
      "Preferred keywords · weight 10%",
      "Semantic relevance · weight 20%",
      "Title & seniority · weight 10%",
      "Format · weight 10%",
      "Quantified impact · weight 10%",
    ]);
    expect(screen.getByTestId("component-required_keywords")).toHaveTextContent("30.0 of 40 points");
  });

  it("shows before → after points and the change for each component", () => {
    render(<BreakdownBars before={before} after={after} />);
    const pref = screen.getByTestId("component-preferred_keywords");
    expect(pref).toHaveTextContent(/0\.0\s*5\.0 of 10 points\s*\(\+5\.0\)/);
    expect(screen.getByTestId("component-required_keywords")).not.toHaveTextContent("(+");
  });
});

describe("KeywordChips", () => {
  it("separates found and missing with headings, icons, and hidden text", () => {
    render(<KeywordChips title="Required" component={before.components[0]} />);
    const group = screen.getByRole("region", { name: "Required" });
    expect(within(group).getByText("Found (3)")).toBeInTheDocument();
    expect(within(group).getByText("Missing (1)")).toBeInTheDocument();
    expect(within(group).getByText("statistics").closest("li")).toHaveTextContent("Missing: statistics");
    expect(within(group).getByText(/implied by a\/b testing/)).toBeInTheDocument();
  });
});

describe("Step 4: score page", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useSession.getState().clearAll();
    const s = useSession.getState();
    s.setResume(resume, { mode: "file", fileName: "cv.pdf" });
    s.setAnalyzed(jd, analysis);
    s.setTailored(tailored);
    s.decide("t1", "approved");
  });

  it("scores approved changes only and shows before vs after with the disclaimer", async () => {
    const score = vi.spyOn(api, "score").mockResolvedValue(response);
    render(<ScorePage />);
    expect(screen.getByText("Estimate only. Real ATS systems vary.")).toBeInTheDocument();

    expect(await screen.findByRole("img", { name: `Your original resume: ${before.total.toFixed(1)} out of 100` })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: `With your 1 approved change: ${after.total.toFixed(1)} out of 100` })).toBeInTheDocument();
    expect(screen.getByText(`+${response.delta!.toFixed(1)} points`)).toBeInTheDocument();

    const [, , sent, , opts] = score.mock.calls[0];
    expect(opts).toMatchObject({ approvedOnly: true });
    expect(sent!.bullets.find((b) => b.id === "t1")!.review).toBe("approved");
    expect(sent!.bullets.find((b) => b.id === "t2")!.review).toBe("pending");
  });

  it("keyword chips show what's found and missing after your changes", async () => {
    vi.spyOn(api, "score").mockResolvedValue(response);
    render(<ScorePage />);
    const preferred = await screen.findByRole("region", { name: "Preferred" });
    expect(within(preferred).getByText("Found (1)")).toBeInTheDocument();
    expect(within(preferred).getByText("dbt / airflow").closest("li")).toHaveTextContent("Found: dbt / airflow");
  });

  it("explains a tie when nothing is approved", async () => {
    useSession.getState().decide("t1", "pending");
    vi.spyOn(api, "score").mockResolvedValue({ before, after: before, delta: 0 });
    render(<ScorePage />);
    expect(await screen.findByText(/no approved changes yet/i)).toBeInTheDocument();
    expect(screen.getByText("No change yet")).toBeInTheDocument();
  });

  it("errors are shown with a retry", async () => {
    const { ApiError } = await import("@/lib/api");
    vi.spyOn(api, "score").mockRejectedValueOnce(new ApiError("backend_down", 0)).mockResolvedValue(response);
    render(<ScorePage />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/can't reach the analysis service/i);
    within(alert).getByRole("button", { name: /try again/i }).click();
    expect(await screen.findByText(`+${response.delta!.toFixed(1)} points`)).toBeInTheDocument();
  });
});
