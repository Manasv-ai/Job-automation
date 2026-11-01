from agent.resume.models import TailoredBullet, TailoredResume, TailoredSection, load_master
from agent.resume.validate import validate_tailored

M = load_master("resume/master_resume.example.json")
JD = "We need a PM with Kubernetes, Agile and Scrum experience. SQL and analytics a plus."


def make(summary="Associate product manager with analytics experience.", skills=("SQL", "Python"),
         b1="Analysed funnel data in SQL to find a checkout drop-off, informing a fix that lifted conversion by 4%."):
    return TailoredResume(summary=summary, skills_order=list(skills),
                          experience=[TailoredSection(id="exp1", bullets=[TailoredBullet(source_id="exp1.b1", text=b1)])])


def test_faithful_passes():
    assert validate_tailored(make(), M, JD) == []

def test_invented_skill():
    assert any("Kubernetes" in e for e in validate_tailored(make(skills=("SQL", "Kubernetes")), M, JD))

def test_invented_number():
    errs = validate_tailored(make(b1="Analysed funnel data in SQL, lifting conversion by 40%."), M, JD)
    assert any("numbers" in e for e in errs)

def test_borrowed_jd_term():
    errs = validate_tailored(make(b1="Analysed funnel data in SQL using Agile and Scrum ceremonies."), M, JD)
    assert any("borrowed" in e for e in errs)

def test_bullet_moved_between_roles():
    t = make(); t.projects = [TailoredSection(id="proj1", bullets=[TailoredBullet(source_id="exp1.b2", text="x")])]
    assert any("different role" in e for e in validate_tailored(t, M, JD))

def test_unknown_source():
    t = make(); t.experience[0].bullets[0].source_id = "nope"
    assert any("does not exist" in e for e in validate_tailored(t, M, JD))
