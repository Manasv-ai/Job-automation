import sys

import pandas as pd
import streamlit as st

from config_loader import load_config, save_config
from db import clear_all_jobs, init_db, job_count, load_all_evaluated_jobs
from freshness import filter_by_evaluated_hours
from excel_exporter import export_jobs_to_excel_bytes
from job_import import merge_descriptions, parse_application_list, parse_csv_rows
from discovery import run_discovery
from pipeline import run_link_import

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

st.set_page_config(
    page_title="Job Agent",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

st.markdown(
    """
    <style>
    .main-header { font-size: 2rem; font-weight: 700; margin-bottom: 0.25rem; }
    .sub-header { color: #64748b; margin-bottom: 1.5rem; }
    div[data-testid="stMetric"] {
        padding: 0.75rem 1rem;
        border-radius: 0.75rem;
        border: 1px solid rgba(148, 163, 184, 0.35);
        background: rgba(148, 163, 184, 0.08);
    }
    .scan-step {
        font-size: 0.95rem;
        margin: 0.35rem 0 0.75rem 0;
        opacity: 0.92;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

config = load_config()
search_cfg = config.setdefault("search_criteria", {})
profile_cfg = config.setdefault("candidate_profile", {})
discovery_cfg = config.setdefault("discovery", {})

st.markdown('<p class="main-header">Job Agent</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="sub-header">Discover jobs from LinkedIn, Indeed, Naukri & Google (free, local Playwright) — scored against your profile.</p>',
    unsafe_allow_html=True,
)

tab_discover, tab_run, tab_results, tab_settings = st.tabs(
    ["Discover", "Import list", "Results", "Settings & export"]
)

with tab_settings:
    st.subheader("Profile & search defaults")
    st.caption("Saved to config.json on your machine. Telegram tokens can also come from environment variables.")

    col_a, col_b = st.columns(2)
    with col_a:
        search_cfg["search_term"] = st.text_input(
            "Job keyword", value=search_cfg.get("search_term", "")
        )
        search_cfg["location"] = st.text_input(
            "Location", value=search_cfg.get("location", "India")
        )
        search_cfg["results_wanted"] = st.slider(
            "Max results per site",
            5,
            50,
            int(search_cfg.get("results_wanted", 20)),
        )
        search_cfg["hours_old"] = st.slider(
            "Max age (hours)", 12, 168, int(search_cfg.get("hours_old", 48))
        )
    with col_b:
        profile_cfg["full_name"] = st.text_input(
            "Name (optional)", value=profile_cfg.get("full_name", "")
        )
        profile_cfg["years_experience"] = st.number_input(
            "Years experience",
            0,
            30,
            int(profile_cfg.get("years_experience", 0)),
        )
        profile_cfg["months_experience"] = st.number_input(
            "Months experience",
            0,
            11,
            int(profile_cfg.get("months_experience", 0)),
        )
        search_cfg["country_indeed"] = st.text_input(
            "Indeed country code", value=search_cfg.get("country_indeed", "India")
        )
        search_cfg["enabled_sites"] = st.multiselect(
            "JobSpy boards",
            ["linkedin", "indeed", "naukri"],
            default=search_cfg.get("enabled_sites") or ["linkedin", "indeed", "naukri"],
            help="Google uses Playwright below, not JobSpy.",
        )

    st.markdown("---")
    st.subheader("Discovery (free)")
    d1, d2 = st.columns(2)
    with d1:
        discovery_cfg["use_jobspy_boards"] = st.checkbox(
            "JobSpy boards", value=bool(discovery_cfg.get("use_jobspy_boards", True))
        )
        discovery_cfg["use_google_playwright"] = st.checkbox(
            "Google Jobs (Playwright)", value=bool(discovery_cfg.get("use_google_playwright", True))
        )
    with d2:
        discovery_cfg["enrich_missing_descriptions"] = st.checkbox(
            "Enrich short JDs via browser",
            value=bool(discovery_cfg.get("enrich_missing_descriptions", True)),
        )
        discovery_cfg["playwright_headless"] = st.checkbox(
            "Headless browser", value=bool(discovery_cfg.get("playwright_headless", True))
        )
    discovery_cfg["enrich_max_per_run"] = st.slider(
        "Max JD fetches per run",
        0,
        30,
        int(discovery_cfg.get("enrich_max_per_run", 15)),
    )
    search_cfg["include_remote_variants"] = st.checkbox(
        "Include remote search variants (JobSpy)",
        value=bool(search_cfg.get("include_remote_variants", True)),
    )
    search_cfg["include_visa_restricted"] = st.checkbox(
        "Include visa-restricted listings",
        value=bool(search_cfg.get("include_visa_restricted", False)),
    )

    roles_raw = st.text_input(
        "Target roles (comma-separated)",
        value=", ".join(profile_cfg.get("target_roles") or []),
    )
    skills_raw = st.text_input(
        "Primary skills (comma-separated)",
        value=", ".join(profile_cfg.get("primary_skills") or []),
    )
    profile_cfg["work_experience_summary"] = st.text_area(
        "Experience summary (used for semantic match)",
        value=profile_cfg.get("work_experience_summary") or "",
        height=100,
    )
    profile_cfg["target_roles"] = [r.strip() for r in roles_raw.split(",") if r.strip()]
    profile_cfg["primary_skills"] = [s.strip() for s in skills_raw.split(",") if s.strip()]

    st.markdown("---")
    st.subheader("Notifications")
    search_cfg["min_match_threshold"] = st.slider(
        "Telegram min match score",
        0.0,
        1.0,
        float(search_cfg.get("min_match_threshold", 0.75)),
        0.05,
    )
    tg1, tg2 = st.columns(2)
    with tg1:
        config["telegram_bot_token"] = st.text_input(
            "Telegram bot token",
            value=config.get("telegram_bot_token") or "",
            type="password",
        )
    with tg2:
        config["telegram_chat_id"] = st.text_input(
            "Telegram chat ID", value=config.get("telegram_chat_id") or ""
        )

    if st.button("Save settings to config.json", type="primary"):
        save_config(config)
        st.success("Settings saved.")

    st.markdown("---")
    if st.button("Clear all stored jobs", type="secondary"):
        clear_all_jobs()
        st.warning("Database cleared. Run a new scan to populate results.")
        st.rerun()

with tab_discover:
    st.subheader("Find jobs that fit your profile")
    st.caption(
        "Uses your **Settings** keyword, location, and profile. "
        "First run installs Chromium via Playwright if needed (`playwright install chromium`)."
    )
    dc1, dc2, dc3 = st.columns(3)
    with dc1:
        disc_force = st.checkbox("Re-score existing links", value=False)
    with dc2:
        disc_telegram = st.checkbox("Telegram alerts", value=False)
    with dc3:
        pass

    if st.button("Run discovery", type="primary", use_container_width=True):
        with st.status("Discovering…", expanded=True) as disc_status:
            progress = st.progress(0.0, text="0% · Starting…")

            def on_disc_progress(pct: int, message: str) -> None:
                progress.progress(pct / 100.0, text=f"{pct}% · {message}")

            summary, reports = run_discovery(
                config=config,
                force_refresh=disc_force,
                send_telegram=disc_telegram,
                on_progress=on_disc_progress,
            )
            disc_status.update(label="Discovery finished", state="complete", expanded=False)

        m1, m2, m3 = st.columns(3)
        m1.metric("Listings found", summary.scraped)
        m2.metric("Newly evaluated", summary.evaluated)
        m3.metric("Skipped (duplicate)", summary.skipped_existing)

        if reports:
            st.markdown("**Source breakdown**")
            st.dataframe(
                [
                    {
                        "Source": r.label,
                        "Count": r.count,
                        "Status": r.status,
                    }
                    for r in reports
                    if r.count or r.error or r.source_id == "google"
                ],
                use_container_width=True,
                hide_index=True,
            )

        if summary.scraped == 0:
            st.warning(
                "No listings returned. If Google shows CAPTCHA, disable headless in Settings "
                "or run again later."
            )
        elif summary.evaluated > 0:
            st.success("Open the **Results** tab. Enable experience filter to hide YoE mismatches.")
        elif summary.skipped_existing > 0:
            st.info("All links already in DB — enable **Re-score existing links**.")

with tab_run:
    st.subheader("Import application list")
    st.caption(
        "Copy from Excel/Sheets or your tracker. Each row needs a **posting URL**. "
        "Paste job description text for accurate experience matching."
    )

    with st.expander("Supported paste formats", expanded=False):
        st.markdown(
            """
**Pipe-separated (recommended)** — one job per line:
```
Associate Product Manager | Myntra | Bengaluru | https://www.linkedin.com/jobs/view/123
Product Analyst | StoneX | Bengaluru | https://...
```

**Links only** — one URL per line (title defaults to “Role”).

**Detailed block** — separate jobs with a `---` line:
```
title: Associate Product Manager
company: Myntra
location: Bengaluru, India
url: https://www.linkedin.com/jobs/view/123
description:
3+ years of experience in working on reporting / business intelligence systems
---
```
            """
        )

    list_text = st.text_area(
        "Applications (title, company, location, link)",
        height=220,
        placeholder="Associate PM | Acme | Bengaluru | https://...\nhttps://www.linkedin.com/jobs/view/...",
    )
    desc_text = st.text_area(
        "Job descriptions (optional)",
        height=160,
        help="One block per job, in the same order as above, separated by --- lines. "
        "Copy the body from LinkedIn for YoE/skills scoring.",
    )

    uploaded = st.file_uploader("Or upload CSV", type=["csv"])
    ic1, ic2, ic3 = st.columns(3)
    with ic1:
        force_refresh = st.checkbox("Re-score if link already saved", value=True)
    with ic2:
        send_telegram = st.checkbox("Send Telegram alerts", value=False)
    with ic3:
        pass

    if st.button("Evaluate pasted list", type="primary", use_container_width=True):
        jobs = parse_application_list(list_text)
        if uploaded is not None:
            csv_jobs = parse_csv_rows(pd.read_csv(uploaded).to_dict(orient="records"))
            jobs = csv_jobs + [j for j in jobs if j.job_url not in {c.job_url for c in csv_jobs}]
        jobs = merge_descriptions(jobs, desc_text)

        if not jobs:
            st.error("No posting links found. Add lines with https:// URLs.")
        else:
            preview = pd.DataFrame(
                [
                    {
                        "title": j.title,
                        "company": j.company,
                        "location": j.location,
                        "site": j.site,
                        "job_url": j.job_url,
                        "desc_chars": len(j.description),
                    }
                    for j in jobs
                ]
            )
            st.dataframe(preview, use_container_width=True, hide_index=True)

            with st.status("Evaluating…", expanded=True) as import_status:
                progress = st.progress(0.0, text="0% · Starting…")

                def on_progress(pct: int, message: str) -> None:
                    progress.progress(pct / 100.0, text=f"{pct}% · {message}")

                summary = run_link_import(
                    jobs=jobs,
                    config=config,
                    force_refresh=force_refresh,
                    send_telegram=send_telegram,
                    on_progress=on_progress,
                )
                import_status.update(label="Evaluation finished", state="complete", expanded=False)

            m1, m2, m3 = st.columns(3)
            m1.metric("Links parsed", len(jobs))
            m2.metric("Newly evaluated", summary.evaluated)
            m3.metric("Skipped (duplicate link)", summary.skipped_existing)

            if summary.evaluated == 0 and summary.skipped_existing > 0:
                st.info("All links were already saved. Enable **Re-score if link already saved**.")
            elif summary.evaluated > 0:
                st.success("Done — open the **Results** tab.")
            if any(len(j.description) < 80 for j in jobs):
                st.warning(
                    "Some jobs have little or no description text. Paste the JD in the "
                    "description box for reliable experience (YoE) filtering."
                )

with tab_results:
    st.subheader("Evaluated openings")

    cand_yoe = int(profile_cfg.get("years_experience", 0)) + int(
        profile_cfg.get("months_experience", 0)
    ) / 12.0

    default_fresh_hours = int(search_cfg.get("hours_old", 24))
    f1, f2, f3, f4 = st.columns([2, 1, 1, 1])
    with f1:
        min_score = st.slider("Min match score", 0.0, 1.0, 0.40, 0.05)
    with f2:
        only_fresh = st.checkbox(
            f"Only evaluated last {default_fresh_hours}h",
            value=True,
            help="Matches Settings → Max age (hours). Hides older DB rows from past runs.",
        )
        current_only = st.checkbox("Current search keyword only", value=False)
        hide_exp_gap = st.checkbox(
            "Hide jobs needing much more experience",
            value=True,
            help=f"Uses parsed required YoE vs your {cand_yoe:.1f} years. Re-run scan with re-score to refresh.",
        )
    with f3:
        site_filter = st.multiselect(
            "Board",
            ["linkedin", "indeed", "google", "manual", "naukri"],
            default=["linkedin", "indeed", "google", "manual", "naukri"],
        )
    with f4:
        visa_filter = st.selectbox(
            "Visa filter",
            ["All", "Global Remote (Visa-Free)", "Standard / Verification Needed", "Restricted (Visa Required)"],
        )

    df = load_all_evaluated_jobs(
        search_query=search_cfg.get("search_term"),
        current_search_only=current_only,
    )
    if only_fresh:
        df = filter_by_evaluated_hours(df, default_fresh_hours)

    if df.empty:
        if only_fresh:
            st.info(
                f"No jobs evaluated in the last **{default_fresh_hours} hours**. "
                "Run **Discover** again, or turn off the freshness filter to see older saves."
            )
        else:
            st.info("No jobs yet. Run **Discover** or use **Import list**.")
    else:
        filtered = df[df["match_score"] >= min_score]
        if hide_exp_gap and "experience_eligible" in filtered.columns:
            filtered = filtered[filtered["experience_eligible"].fillna(1).astype(int) == 1]
        elif hide_exp_gap and "exp_score" in filtered.columns:
            filtered = filtered[filtered["exp_score"] >= 0.5]
        if hide_exp_gap and "req_yoe" in filtered.columns:
            def _req_yoe_num(val):
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    return None
                s = str(val).strip()
                if not s or s.lower() == "not specified":
                    return None
                try:
                    return int(float(s))
                except ValueError:
                    return None

            req_nums = filtered["req_yoe"].map(_req_yoe_num)
            allowed = req_nums.isna() | (req_nums <= max(cand_yoe + 1.0, 1.0))
            filtered = filtered[allowed]

        if site_filter:
            filtered = filtered[filtered["site"].isin(site_filter)]
        if visa_filter != "All":
            filtered = filtered[filtered["visa_status"] == visa_filter]

        avg_score = filtered["match_score"].mean() if len(filtered) else 0.0
        c1, c2, c3 = st.columns(3)
        c1.metric("Showing", len(filtered))
        c2.metric("In database", job_count())
        c3.metric("Avg match (filtered)", f"{avg_score:.0%}")

        display_cols = [
            "match_score",
            "title_score",
            "exp_score",
            "semantic_score",
            "title",
            "company",
            "location",
            "visa_status",
            "key_matches",
            "req_yoe",
            "site",
            "job_url",
            "scraped_at",
        ]
        present_cols = [c for c in display_cols if c in filtered.columns]

        st.dataframe(
            filtered[present_cols],
            column_config={
                "match_score": st.column_config.ProgressColumn(
                    "Match", format="%.0f%%", min_value=0, max_value=1
                ),
                "title_score": st.column_config.NumberColumn("Title fit", format="%.2f"),
                "exp_score": st.column_config.NumberColumn("Exp fit", format="%.2f"),
                "semantic_score": st.column_config.NumberColumn("Semantic", format="%.2f"),
                "job_url": st.column_config.LinkColumn("Apply"),
            },
            use_container_width=True,
            height=min(520, 80 + 35 * max(len(filtered), 1)),
        )

        export_col1, export_col2 = st.columns(2)
        records = filtered.to_dict(orient="records")
        with export_col1:
            csv_bytes = filtered.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download CSV",
                data=csv_bytes,
                file_name="evaluated_jobs.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with export_col2:
            if records:
                st.download_button(
                    "Download Excel",
                    data=export_jobs_to_excel_bytes(records),
                    file_name="evaluated_jobs.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
