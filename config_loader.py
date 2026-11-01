import json
import os
from copy import deepcopy
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
EXAMPLE_PATH = Path(__file__).resolve().parent / "config.example.json"

DEFAULT_CONFIG = {
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "search_criteria": {
        "search_term": "Software Engineer",
        "location": "India",
        "results_wanted": 20,
        "hours_old": 48,
        "min_match_threshold": 0.75,
        "country_indeed": "India",
        "include_visa_restricted": False,
        "include_remote_variants": True,
        "enabled_sites": ["linkedin", "indeed", "naukri"],
    },
    "discovery": {
        "use_jobspy_boards": True,
        "use_google_playwright": True,
        "enrich_missing_descriptions": True,
        "enrich_max_per_run": 15,
        "playwright_headless": True,
    },
    "candidate_profile": {
        "full_name": "",
        "years_experience": 1,
        "months_experience": 0,
        "target_roles": ["Software Engineer"],
        "primary_skills": ["Python", "SQL"],
        "work_experience_summary": "",
    },
}


def _apply_env_overrides(config: dict) -> dict:
    cfg = deepcopy(config)
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if token:
        cfg["telegram_bot_token"] = token
    if chat:
        cfg["telegram_chat_id"] = chat
    return cfg


def load_config(path: Path | None = None) -> dict:
    path = path or CONFIG_PATH
    if not path.exists():
        if EXAMPLE_PATH.exists():
            with open(EXAMPLE_PATH, encoding="utf-8") as f:
                base = json.load(f)
        else:
            base = deepcopy(DEFAULT_CONFIG)
        save_config(base, path)
        return _apply_env_overrides(base)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    merged = deepcopy(DEFAULT_CONFIG)
    merged.update({k: v for k, v in data.items() if k in merged})
    if "search_criteria" in data:
        merged["search_criteria"].update(data["search_criteria"])
    if "candidate_profile" in data:
        merged["candidate_profile"].update(data["candidate_profile"])
    if "discovery" in data:
        merged["discovery"].update(data["discovery"])
    return _apply_env_overrides(merged)


def save_config(config: dict, path: Path | None = None) -> None:
    path = path or CONFIG_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def profile_from_config(config: dict) -> dict:
    p = config.get("candidate_profile", {})
    return {
        "target_roles": list(p.get("target_roles") or []),
        "primary_skills": list(p.get("primary_skills") or []),
        "years_experience": int(p.get("years_experience", 0)),
        "months_experience": int(p.get("months_experience", 0)),
        "work_experience_summary": p.get("work_experience_summary") or "",
    }
