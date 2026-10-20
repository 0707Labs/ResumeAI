/**
 * App state, kept in sessionStorage so a refresh doesn't lose work, and gone when
 * the tab closes. `clearAll` wipes it immediately for privacy.
 */
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type {
  GapAnalysis,
  JobDescription,
  MentorAdvice,
  Resume,
  ReviewStatus,
  ScoreResponse,
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
  decisions: Record<string, ReviewStatus>; // keyed by tailored bullet id
  score: ScoreResponse | null;
  mentor: MentorAdvice | null;
};

type Actions = {
  setResume: (resume: Resume, input: ResumeInput) => void;
  clearResume: () => void;
  setJobInputs: (patch: Partial<Pick<Data, "jdText" | "jobTitle" | "company">>) => void;
  setAnalyzed: (jd: JobDescription, analysis: GapAnalysis) => void;
  setAnswer: (questionId: string, answer: Answer) => void;
  /** Answers were saved on the server; anything tailored before is now stale. */
  setAnswered: (analysis: GapAnalysis) => void;
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
  score: null,
  mentor: null,
};

// Anything computed from the resume or JD is stale once either changes.
const DOWNSTREAM: Partial<Data> = {
  jd: null,
  analysis: null,
  answers: {},
  tailored: null,
  decisions: {},
  score: null,
  mentor: null,
};

export const useSession = create<Data & Actions>()(
  persist(
    (set) => ({
      ...EMPTY,
      setResume: (resume, resumeInput) => set({ resume, resumeInput, ...DOWNSTREAM }),
      clearResume: () => set({ resume: null, resumeInput: null, ...DOWNSTREAM }),
      setJobInputs: (patch) => set((s) => ({ ...patch, ...(s.analysis ? DOWNSTREAM : {}) })),
      setAnalyzed: (jd, analysis) =>
        set({ jd, analysis, answers: {}, tailored: null, decisions: {}, score: null, mentor: null }),
      setAnswer: (id, answer) => set((s) => ({ answers: { ...s.answers, [id]: answer } })),
      setAnswered: (analysis) => set({ analysis, tailored: null, decisions: {}, score: null, mentor: null }),
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
