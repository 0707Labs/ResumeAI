/**
 * App state, kept in sessionStorage so a refresh doesn't lose work, and gone when
 * the tab closes. `clearAll` wipes it immediately for privacy.
 */
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { type Decisions, approveAllVerified, decide } from "./review";
import type {
  GapAnalysis,
  JobDescription,
  MentorAdvice,
  Resume,
  ReviewStatus,
  ScoreResponse,
  TailoredBullet,
  TailoredResume,
} from "./schemas";

export const STORAGE_KEY = "resume-tailor-session";

export type AnswerChoice = "yes" | "no" | "skip";
export type Answer = { choice: AnswerChoice; text: string };

export type ResumeInput =
  | { mode: "file"; fileName: string }
  | { mode: "paste"; text: string };

type Data = {
  resume: Resume | null;
  resumeInput: ResumeInput | null;
  jdText: string;
  jobTitle: string;
  company: string;
  jd: JobDescription | null;
  analysis: GapAnalysis | null;
  answers: Record<string, Answer>; // keyed by question id
  tailored: TailoredResume | null;
  decisions: Decisions; // keyed by tailored bullet id
  edited: Record<string, true>; // tailored bullet ids the user rewrote by hand
  score: ScoreResponse | null;
  mentor: MentorAdvice | null;
  checked: Record<string, boolean>; // mentor checklist: "action:a1", "plan:w1t2"
};

type Actions = {
  setResume: (resume: Resume, input: ResumeInput) => void;
  clearResume: () => void;
  setJobInputs: (patch: Partial<Pick<Data, "jdText" | "jobTitle" | "company">>) => void;
  setAnalyzed: (jd: JobDescription, analysis: GapAnalysis) => void;
  setAnswer: (questionId: string, answer: Answer) => void;
  /** Answers were saved on the server; anything tailored before is now stale. */
  setAnswered: (analysis: GapAnalysis) => void;
  setTailored: (tailored: TailoredResume) => void;
  decide: (bulletId: string, status: ReviewStatus) => void;
  approveAllVerified: () => void;
  /** Replace one bullet after a manual edit (re-verified); its decision resets. */
  replaceBullet: (bullet: TailoredBullet) => void;
  setSummaryReview: (status: ReviewStatus) => void;
  setScore: (score: ScoreResponse | null) => void;
  setMentor: (mentor: MentorAdvice) => void;
  toggleChecked: (key: string, value: boolean) => void;
  clearAll: () => void;
};

const EMPTY: Data = {
  resume: null,
  resumeInput: null,
  jdText: "",
  jobTitle: "",
  company: "",
  jd: null,
  analysis: null,
  answers: {},
  tailored: null,
  decisions: {},
  edited: {},
  score: null,
  mentor: null,
  checked: {},
};

// Anything computed from the resume or JD is stale once either changes.
const DOWNSTREAM: Partial<Data> = {
  jd: null,
  analysis: null,
  answers: {},
  tailored: null,
  decisions: {},
  edited: {},
  score: null,
  mentor: null,
  checked: {},
};

export const useSession = create<Data & Actions>()(
  persist(
    (set) => ({
      ...EMPTY,
      setResume: (resume, resumeInput) => set({ resume, resumeInput, ...DOWNSTREAM }),
      clearResume: () => set({ resume: null, resumeInput: null, ...DOWNSTREAM }),
      setJobInputs: (patch) => set((s) => ({ ...patch, ...(s.analysis ? DOWNSTREAM : {}) })),
      setAnalyzed: (jd, analysis) =>
        set({ jd, analysis, answers: {}, tailored: null, decisions: {}, edited: {}, score: null, mentor: null, checked: {} }),
      setAnswer: (id, answer) => set((s) => ({ answers: { ...s.answers, [id]: answer } })),
      setAnswered: (analysis) => set({ analysis, tailored: null, decisions: {}, edited: {}, score: null, mentor: null, checked: {} }),
      setTailored: (tailored) => set({ tailored, decisions: {}, edited: {}, score: null }),
      decide: (id, status) => set((s) => {
        const b = s.tailored?.bullets.find((x) => x.id === id);
        return b ? { decisions: decide(s.decisions, b, status) } : {};
      }),
      approveAllVerified: () => set((s) => (s.tailored ? { decisions: approveAllVerified(s.tailored, s.decisions) } : {})),
      replaceBullet: (bullet) => set((s) => {
        if (!s.tailored) return {};
        const { [bullet.id]: _dropped, ...rest } = s.decisions;
        return {
          tailored: { ...s.tailored, bullets: s.tailored.bullets.map((b) => (b.id === bullet.id ? bullet : b)) },
          decisions: rest,
          edited: { ...s.edited, [bullet.id]: true },
        };
      }),
      setSummaryReview: (status) => set((s) => {
        if (!s.tailored) return {};
        if (status === "approved" && !s.tailored.summary_verification?.passed) return {};
        return { tailored: { ...s.tailored, summary_review: status } };
      }),
      setScore: (score) => set({ score }),
      setMentor: (mentor) => set({ mentor }), // ticks survive a refresh: ids are stable
      toggleChecked: (key, value) => set((s) => ({ checked: { ...s.checked, [key]: value } })),
      clearAll: () => {
        set({ ...EMPTY });
        try {
          sessionStorage.removeItem(STORAGE_KEY);
        } catch {
          /* storage blocked: nothing persisted anyway */
        }
      },
    }),
    {
      name: STORAGE_KEY,
      storage: createJSONStorage(() => sessionStorage),
      // Rehydrated on the client (see SessionHydrator) to avoid SSR mismatches.
      skipHydration: true,
      version: 1,
    },
  ),
);
