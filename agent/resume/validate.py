"""Guardrails: a tailored resume may not contain anything the master resume doesn't support.

This is a heuristic safety net (numbers, skills, borrowed JD terminology, structure).
The human review step in Notion remains the real gate.
"""
from __future__ import annotations

import re

from .models import MasterResume, TailoredResume

_NUM = re.compile(r"\d[\d,.]*\s?(?:%|x|k|m|cr|lpa)?", re.I)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]*")


def _numbers(text: str) -> set[str]:
    return {re.sub(r"[\s,]", "", m.group(0).lower()).rstrip(".") for m in _NUM.finditer(text)}


def _tokens(text: str) -> set[str]:
    return {w.lower().strip(".-/") for w in _WORD.findall(text)}


def _techish(text: str) -> set[str]:
    """Capitalised mid-sentence words, ALLCAPS, or tokens with digits/+/#/. — likely tools or buzzwords."""
    out: set[str] = set()
    for sent in re.split(r"(?<=[.!?])\s+", text):
        words = _WORD.findall(sent)
        for i, w in enumerate(words):
            if len(w) < 2:
                continue
            if (i > 0 and w[0].isupper()) or w.isupper() or re.search(r"[0-9+#]", w):
                out.add(w.lower().strip(".-/"))
    return out


def validate_tailored(t: TailoredResume, master: MasterResume, job_description: str = "") -> list[str]:
    errors: list[str] = []
    master_tokens = _tokens(master.full_text())
    jd_tokens = _tokens(job_description)
    idx = master.bullet_index()
    master_skills = {s.lower() for s in master.skills}

    # skills must be a subset
    for s in t.skills_order:
        if s.lower() not in master_skills:
            errors.append(f"Skill '{s}' is not in the master resume.")

    # structure: sections must exist; bullets must belong to their section
    valid_exp = {e.id for e in master.experience}
    valid_proj = {p.id for p in master.projects}
    for sec_list, valid, kind in ((t.experience, valid_exp, "experience"), (t.projects, valid_proj, "project")):
        for sec in sec_list:
            if sec.id not in valid:
                errors.append(f"Unknown {kind} id '{sec.id}'.")
                continue
            for b in sec.bullets:
                src = idx.get(b.source_id)
                if not src:
                    errors.append(f"Bullet source_id '{b.source_id}' does not exist.")
                    continue
                if src[0] != sec.id:
                    errors.append(f"Bullet '{b.source_id}' moved into a different role/project ('{sec.id}').")
                    continue
                errors += _check_text(b.text, src[1], master_tokens, jd_tokens, f"bullet {b.source_id}")

    errors += _check_text(t.summary, master.summary + " " + master.full_text(), master_tokens, jd_tokens, "summary")
    if not any(sec.bullets for sec in t.experience + t.projects):
        errors.append("Tailored resume has no bullets.")
    return errors


def _check_text(new: str, source: str, master_tokens: set[str], jd_tokens: set[str], label: str) -> list[str]:
    errs = []
    bad_nums = _numbers(new) - _numbers(source)
    if bad_nums:
        errs.append(f"{label}: numbers not supported by the source: {sorted(bad_nums)}")
    # terms that appear in the JD, look technical, and are nowhere in the master resume
    borrowed = {w for w in _techish(new) if w in jd_tokens and w not in master_tokens}
    if borrowed:
        errs.append(f"{label}: terms borrowed from the job description but absent from your resume: {sorted(borrowed)}")
    return errs
