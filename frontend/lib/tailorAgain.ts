import type { TailoringDetail } from "./schemas";
import { useSession } from "./store";

/** Start a fresh tailoring from an earlier one's resume and job description (a new
 * analysis; nothing from the old run carries over). False when its text was purged. */
export function loadForTailoring(t: TailoringDetail): boolean {
  if (!t.resume || !t.jd) return false;
  const s = useSession.getState();
  s.clearAll();
  s.setResume(t.resume, { mode: "file", fileName: [t.job_title, t.company].filter(Boolean).join(" at ") || "Earlier tailoring" });
  s.setJobInputs({ jdText: t.jd.raw_text, jobTitle: t.job_title ?? "", company: t.company ?? "" });
  return true;
}
