"""Clarifying questions (rule 6) and applying the candidate's answers.

Questions are asked for every MISSING item, for IMPLIED items (to confirm before
the tailor may name the skill), and for skills listed in Skills but never shown
in a bullet. Wording is neutral: it never presumes the candidate has the skill.
"""

from app.models import (
    ClarifyingQuestion,
    GapAnalysis,
    GapItem,
    GapStatus,
    RequirementCategory,
    Resume,
)

MAX_ANSWER_CHARS = 2000


class AnswerError(ValueError):
    pass


def _question_text(item: GapItem, resume: Resume) -> str | None:
    kws = item.missing_keywords
    if item.status == GapStatus.MISSING:
        if item.category == RequirementCategory.EDUCATION:
            return (f'The role asks for: "{item.requirement_text}". Do you have a degree or '
                    f"equivalent qualification that isn't on your resume? If not, just say no.")
        if item.category == RequirementCategory.CERTIFICATION:
            return (f'The role asks for: "{item.requirement_text}". Do you hold this '
                    f"certification (or are you working toward it)? If not, just say no.")
        if "years" in item.rationale and not kws:
            return (f'The role asks for: "{item.requirement_text}". Is there relevant '
                    f"experience missing from your resume (freelance, part-time, research, "
                    f"open source)? If so, where and for how long? If not, just say no.")
        if kws:
            return (f"The role asks for {_join(kws)}. Have you used "
                    f"{'it' if len(kws) == 1 else 'any of these'} at work, in a project, or in "
                    f"coursework? If yes, where and what did you do with it? If not, just say no.")
        return (f'The role mentions: "{item.requirement_text}". Do you have a concrete '
                f"example of this from your work? If not, just say no.")
    if item.status == GapStatus.IMPLIED:
        if kws and item.evidence_bullet_ids:
            bullet = resume.bullet_by_id(item.evidence_bullet_ids[0])
            quote = f' Your bullet "{bullet.text}" is related.' if bullet else ""
            return (f"The role asks for {_join(kws)}.{quote} Did you use "
                    f"{_join(kws)} directly? If yes, briefly how. If not, just say no.")
        if kws:
            return (f"The role asks for {_join(kws)}. Your resume suggests related experience "
                    f"but doesn't name it. Have you used {_join(kws)} directly? If yes, "
                    f"briefly how. If not, just say no.")
        return (f'The role mentions: "{item.requirement_text}". Some of your bullets look '
                f"related. Can you describe a specific example? If not, just say no.")
    # EVIDENCED, but only in the Skills list: ask for a concrete use.
    listed_only = [s for s in item.evidence_skills if s in item.matched_keywords]
    if listed_only and not item.evidence_bullet_ids:
        return (f"You list {_join(listed_only)} in your skills but no bullet shows it in use. "
                f"Where did you use it, and what was the result? (Optional, but it makes the "
                f"tailored resume stronger.)")
    return None


def assign_questions(items: list[GapItem], resume: Resume) -> list[GapItem]:
    out: list[GapItem] = []
    n = 0
    for item in items:
        if item.decided_by == "llm" and item.question and item.question.question != "pending":
            text = item.question.question
        else:
            text = _question_text(item, resume)
        if text is None:
            out.append(item.model_copy(update={"question": None}))
            continue
        n += 1
        q = ClarifyingQuestion(id=f"q{n}", requirement_id=item.requirement_id, question=text)
        out.append(item.model_copy(update={"question": q}))
    return out


def apply_answers(analysis: GapAnalysis, answers: dict[str, str]) -> GapAnalysis:
    """Record the candidate's answers. Statuses don't change: an answer is a new,
    candidate-supplied source the tailor may cite (source_answer_ids), not a
    retroactive edit of what the resume says."""
    known = {q.id for q in analysis.questions()}
    unknown = sorted(set(answers) - known)
    if unknown:
        raise AnswerError(f"unknown question id(s): {', '.join(unknown)}")
    too_long = [qid for qid, a in answers.items() if len(a) > MAX_ANSWER_CHARS]
    if too_long:
        raise AnswerError(f"answer too long for: {', '.join(sorted(too_long))}")
    items = []
    for item in analysis.items:
        if item.question and item.question.id in answers:
            answer = answers[item.question.id].strip() or None
            item = item.model_copy(update={
                "question": item.question.model_copy(update={"answer": answer})})
        items.append(item)
    return analysis.model_copy(update={"items": items})


def _join(words: list[str]) -> str:
    if len(words) <= 2:
        return " or ".join(words) if len(words) == 2 else words[0]
    return ", ".join(words[:-1]) + f", or {words[-1]}"
