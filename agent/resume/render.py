"""ATS-friendly DOCX: single column, standard headings, no tables/graphics."""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Pt


def render_docx(merged: dict, path: str) -> str:
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10.5)

    doc.add_heading(merged["name"], level=0)
    contact = " | ".join(x for x in [merged.get("email"), merged.get("phone"), merged.get("location"), *merged.get("links", [])] if x)
    if contact:
        doc.add_paragraph(contact)

    def section(title: str):
        doc.add_heading(title, level=1)

    if merged.get("summary"):
        section("Summary")
        doc.add_paragraph(merged["summary"])
    if merged.get("skills"):
        section("Skills")
        doc.add_paragraph(", ".join(merged["skills"]))
    if merged.get("experience"):
        section("Experience")
        for e in merged["experience"]:
            p = doc.add_paragraph()
            p.add_run(f"{e['title']}, {e['company']}").bold = True
            dates = " – ".join(x for x in [e.get("start"), e.get("end")] if x)
            if dates:
                p.add_run(f"  ({dates})")
            for b in e["bullets"]:
                doc.add_paragraph(b, style="List Bullet")
    if merged.get("projects"):
        section("Projects")
        for pr in merged["projects"]:
            doc.add_paragraph().add_run(pr["name"]).bold = True
            for b in pr["bullets"]:
                doc.add_paragraph(b, style="List Bullet")
    if merged.get("education"):
        section("Education")
        for ed in merged["education"]:
            doc.add_paragraph(f"{ed['degree']}, {ed['school']} {('(' + ed['years'] + ')') if ed.get('years') else ''}".strip())

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path
