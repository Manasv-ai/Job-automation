import re
from collections.abc import Callable
from functools import lru_cache

from rapidfuzz import fuzz
from sentence_transformers import SentenceTransformer, util

MODEL_NAME = "all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)


class WeightedJobMatcher:
    def __init__(self, candidate_profile: dict, model: SentenceTransformer | None = None):
        self.profile = candidate_profile
        self.model = model or get_embedding_model()

        skills_text = ", ".join(self.profile.get("primary_skills", []))
        summary_text = self.profile.get("work_experience_summary", "")
        self.candidate_vec = self.model.encode(
            f"{skills_text}. {summary_text}", convert_to_tensor=True
        )

    def explain_skills(self, description: str) -> tuple[str, str]:
        desc_lower = str(description).lower()
        skills = self.profile.get("primary_skills") or []
        matched = [s for s in skills if s.lower() in desc_lower]
        missing = [s for s in skills if s.lower() not in desc_lower]
        key_matches = ", ".join(matched) if matched else "None detected"
        missing_skills = ", ".join(missing[:8]) if missing else "None"
        return key_matches, missing_skills

    def _infer_yoe_from_title(self, job_title: str) -> int:
        title = job_title.lower()
        junior_markers = (
            "associate",
            "assistant",
            "junior",
            "jr ",
            "entry",
            "graduate",
            "intern",
            "trainee",
            "analyst i",
            "level 1",
            "0-1",
            "0 to 1",
            "1-2",
        )
        if any(m in title for m in junior_markers):
            return 0

        if any(m in title for m in ("principal", "staff", "director", "head of")):
            return 8
        if any(m in title for m in ("senior", "sr.", " sr ", "lead")):
            return 5
        if "manager" in title and "associate" not in title:
            return 3
        return 0

    def extract_required_yoe(self, job_title: str, description: str) -> int:
        combined = f"{job_title}. {description or ''}"
        if not combined.strip():
            return 0

        clean_text = (
            combined.replace("\xa0", " ")
            .replace("\r", " ")
            .replace("\n", " ")
            .replace("–", "-")
            .replace("—", "-")
        )

        extracted: list[int] = []

        range_patterns = [
            r"(\d+)\s*[-to]+\s*(\d+)\s*(?:\+?\s*)?(?:years?|yrs?)",
            r"(\d+)\s*to\s*(\d+)\s*(?:years?|yrs?)",
        ]
        for pattern in range_patterns:
            for low, high in re.findall(pattern, clean_text, re.IGNORECASE):
                try:
                    extracted.extend(int(x) for x in (low, high) if int(x) <= 15)
                except ValueError:
                    pass

        scalar_patterns = [
            r"(\d+)\+\s*(?:years?|yrs?)",
            r"(\d+)\s*(?:years?|yrs?)\s*\+",
            r"(?:at least|minimum of|minimum|min\.?|with)\s+(\d+)\+?\s*(?:years?|yrs?)",
            r"(\d+)\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:experience|exp\.?|work|background|product|ownership|management|infrastructure|engineering|related)",
            r"(\d+)\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:experience\s+)?(?:in|with)",
            r"(\d+)\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:professional|relevant|software|industry)",
            r"experience\s*(?:of\s*)?(\d+)\+?\s*(?:years?|yrs?)",
        ]
        for pattern in scalar_patterns:
            for m in re.findall(pattern, clean_text, re.IGNORECASE):
                try:
                    val = int(m)
                    if val <= 15:
                        extracted.append(val)
                except ValueError:
                    pass

        if extracted:
            return max(extracted)

        return self._infer_yoe_from_title(job_title)

    def compute_exp_score(
        self,
        job_title: str,
        req_yoe: int,
        cand_yoe: float,
        title_score: float,
        description_len: int = 0,
    ) -> float:
        exp_score = 1.0

        if self._title_is_senior_mismatch(job_title, title_score) and cand_yoe < 3.0:
            exp_score = 0.0
        elif req_yoe > 0:
            gap = req_yoe - cand_yoe
            if gap >= 1.0:
                exp_score = max(0.0, 1.0 - (gap / max(req_yoe, 1)))
            if req_yoe >= cand_yoe + 2:
                exp_score = 0.0
            elif req_yoe >= cand_yoe + 1:
                exp_score = min(exp_score, 0.12)
        elif description_len < 120 and cand_yoe < 2.0:
            # JD text missing — do not assume "no experience required"
            exp_score = min(exp_score, 0.25)

        if title_score < 0.40:
            exp_score = min(exp_score, 0.10)

        return round(exp_score, 2)

    def is_experience_eligible(self, req_yoe: int, cand_yoe: float, description_len: int) -> bool:
        if req_yoe > 0 and req_yoe > cand_yoe + 1.0:
            return False
        if description_len < 120 and cand_yoe < 2.0 and req_yoe == 0:
            return False
        return True

    def cap_score_for_experience(
        self, match_score: float, req_yoe: int, cand_yoe: float, exp_score: float
    ) -> float:
        if req_yoe > cand_yoe + 1.0:
            return min(match_score, 0.35)
        if exp_score <= 0.12:
            return min(match_score, 0.38)
        return match_score

    def _title_is_senior_mismatch(self, job_title: str, title_score: float) -> bool:
        title_lower = job_title.lower()
        target_roles = [r.lower() for r in self.profile.get("target_roles", [])]
        targets_manager = any("manager" in r for r in target_roles)

        senior_terms = ["senior", "lead", "staff", "principal", "head", "director"]
        if title_lower.startswith("sr ") or " sr " in title_lower:
            return title_score < 0.55
        if not targets_manager:
            senior_terms.append("manager")

        if title_score >= 0.55:
            return False
        return any(term in title_lower for term in senior_terms)

    def evaluate(self, job_title: str, company: str, description: str) -> dict:
        years = int(self.profile.get("years_experience", 0))
        months = int(self.profile.get("months_experience", 0))
        cand_yoe = round(years + (months / 12.0), 2)

        target_roles = self.profile.get("target_roles", [])
        title_score = max(
            [fuzz.token_set_ratio(role.lower(), job_title.lower()) / 100.0 for role in target_roles]
            or [0.0]
        )

        desc_text = str(description or "")
        desc_len = len(desc_text.strip())
        req_yoe = self.extract_required_yoe(job_title, desc_text)
        exp_score = self.compute_exp_score(
            job_title, req_yoe, cand_yoe, title_score, description_len=desc_len
        )

        embed_text = desc_text[:2000] if len(desc_text) > 40 else job_title
        job_vec = self.model.encode(embed_text, convert_to_tensor=True)
        similarity_score = float(util.cos_sim(self.candidate_vec, job_vec)[0][0])
        similarity_score = max(0.0, min(1.0, similarity_score))

        final_score = round(
            (exp_score * 0.40) + (similarity_score * 0.40) + (title_score * 0.20), 2
        )
        final_score = self.cap_score_for_experience(final_score, req_yoe, cand_yoe, exp_score)
        key_matches, missing_skills = self.explain_skills(description)

        return {
            "match_score": final_score,
            "required_yoe": req_yoe if req_yoe > 0 else "Not Specified",
            "exp_score": round(exp_score, 2),
            "semantic_score": round(similarity_score, 2),
            "title_score": round(title_score, 2),
            "key_matches": key_matches,
            "missing_skills": missing_skills,
            "experience_eligible": self.is_experience_eligible(req_yoe, cand_yoe, desc_len),
        }

    def evaluate_batch(
        self,
        jobs: list[dict],
        on_progress: Callable[[int, int], None] | None = None,
        chunk_size: int = 12,
    ) -> list[dict]:
        if not jobs:
            return []

        years = int(self.profile.get("years_experience", 0))
        months = int(self.profile.get("months_experience", 0))
        cand_yoe = round(years + (months / 12.0), 2)
        target_roles = self.profile.get("target_roles", [])

        results: list[dict] = []
        total = len(jobs)
        for start in range(0, total, chunk_size):
            chunk = jobs[start : start + chunk_size]
            texts = []
            for j in chunk:
                desc = str(j.get("description", ""))
                title = str(j.get("title", ""))
                texts.append(desc[:2000] if len(desc) > 40 else title)

            job_vecs = self.model.encode(texts, convert_to_tensor=True, batch_size=16)
            for idx, job in enumerate(chunk):
                title = str(job.get("title", ""))
                description = str(job.get("description", "") or "")
                desc_len = len(description.strip())

                title_score = max(
                    [fuzz.token_set_ratio(role.lower(), title.lower()) / 100.0 for role in target_roles]
                    or [0.0]
                )
                req_yoe = self.extract_required_yoe(title, description)
                exp_score = self.compute_exp_score(
                    title, req_yoe, cand_yoe, title_score, description_len=desc_len
                )

                similarity_score = float(util.cos_sim(self.candidate_vec, job_vecs[idx : idx + 1])[0][0])
                similarity_score = max(0.0, min(1.0, similarity_score))
                final_score = round(
                    (exp_score * 0.40) + (similarity_score * 0.40) + (title_score * 0.20), 2
                )
                final_score = self.cap_score_for_experience(final_score, req_yoe, cand_yoe, exp_score)
                key_matches, missing_skills = self.explain_skills(description)
                results.append(
                    {
                        "match_score": final_score,
                        "required_yoe": req_yoe if req_yoe > 0 else "Not Specified",
                        "exp_score": round(exp_score, 2),
                        "semantic_score": round(similarity_score, 2),
                        "title_score": round(title_score, 2),
                        "key_matches": key_matches,
                        "missing_skills": missing_skills,
                        "experience_eligible": self.is_experience_eligible(
                            req_yoe, cand_yoe, desc_len
                        ),
                    }
                )

            if on_progress:
                on_progress(min(start + len(chunk), total), total)

        return results
