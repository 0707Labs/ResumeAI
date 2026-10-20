import type { GapAnalysis, JobDescription, Resume } from "@/lib/schemas";

export const resume: Resume = {
  name: "Asha Rao",
  contact: { email: "asha@example.com", phone: null, location: null, links: [] },
  summary: null,
  skills: ["SQL"],
  sections: [{
    kind: "experience",
    heading: "Experience",
    entries: [{
      id: "exp1", title: "Data Analyst", organization: "Acme", location: null,
      start_date: "Jan 2022", end_date: "Present",
      bullets: [{ id: "exp1.b1", text: "Cut weekly reporting time by 30% with SQL" }],
    }],
  }],
  raw_text: "Asha Rao\nExperience\n• Cut weekly reporting time by 30% with SQL",
  parse_warnings: [],
};

export const jd: JobDescription = {
  title: "Analyst",
  company: null,
  seniority: "mid",
  years_experience_min: null,
  responsibilities: [],
  requirements: [{ id: "req1", text: "SQL", priority: "required", category: "skill", keywords: ["sql"] }],
  raw_text: "Analyst\nRequirements\n- SQL",
};

export const analysis: GapAnalysis = {
  items: [{
    requirement_id: "req1", requirement_text: "SQL", priority: "required", category: "skill",
    status: "evidenced", evidence_bullet_ids: ["exp1.b1"], evidence_entry_ids: [], evidence_skills: [],
    matched_keywords: ["sql"], missing_keywords: [], rationale: "SQL named in your bullets.",
    question: null, decided_by: "rules",
  }],
  candidate_years_experience: 3,
  notes: [],
  counts: { evidenced: 1, implied: 0, missing: 0 },
  required_coverage: 1,
};

export const JD_TEXT = "Senior Data Analyst\nRequirements\n- 5+ years of SQL and Python\n- Tableau dashboards\n- Statistics and A/B testing";
