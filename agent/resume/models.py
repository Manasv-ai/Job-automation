from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class Bullet(BaseModel):
    id: str
    text: str


class Experience(BaseModel):
    id: str
    company: str
    title: str
    start: str = ""
    end: str = ""
    location: str = ""
    bullets: list[Bullet]


class Project(BaseModel):
    id: str
    name: str
    bullets: list[Bullet]


class Education(BaseModel):
    school: str
    degree: str
    years: str = ""


class MasterResume(BaseModel):
    """Single source of truth. The agent may only SELECT / REORDER / REWORD from this."""
    name: str
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[str] = Field(default_factory=list)
    summary: str = ""
    skills: list[str]
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)

    def bullet_index(self) -> dict[str, tuple[str, str]]:
        """bullet_id -> (parent_id, text)"""
        idx: dict[str, tuple[str, str]] = {}
        for e in self.experience:
            for b in e.bullets:
                idx[b.id] = (e.id, b.text)
        for p in self.projects:
            for b in p.bullets:
                idx[b.id] = (p.id, b.text)
        return idx

    def full_text(self) -> str:
        parts = [self.summary, " ".join(self.skills)]
        for e in self.experience:
            parts += [e.company, e.title, *[b.text for b in e.bullets]]
        for p in self.projects:
            parts += [p.name, *[b.text for b in p.bullets]]
        for ed in self.education:
            parts += [ed.school, ed.degree]
        return " ".join(parts)


def load_master(path: str) -> MasterResume:
    return MasterResume.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


# ---- what the LLM is allowed to return ------------------------------------
class TailoredBullet(BaseModel):
    source_id: str = Field(description="id of the master-resume bullet this is derived from")
    text: str = Field(description="reworded bullet; may only use facts present in the source bullet")


class TailoredSection(BaseModel):
    id: str = Field(description="experience id or project id from the master resume")
    bullets: list[TailoredBullet]


class TailoredResume(BaseModel):
    summary: str = Field(description="2-3 sentence summary using only facts from the master resume")
    skills_order: list[str] = Field(description="subset of master skills, most job-relevant first")
    experience: list[TailoredSection]
    projects: list[TailoredSection] = Field(default_factory=list)
    gaps: list[str] = Field(
        default_factory=list,
        description="skills/requirements in the job description that are NOT in the master resume",
    )
    rationale: str = Field(default="", description="1-3 sentences: what was emphasised and why")
