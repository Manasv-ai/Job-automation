import pandas as pd


def cell_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    return text


def build_job_description(row) -> str:
    """Combine all text JobSpy provides for YoE / skill parsing."""
    parts = [
        cell_str(row.get("description")),
        cell_str(row.get("experience_range")),
        cell_str(row.get("job_level")),
        cell_str(row.get("job_function")),
        cell_str(row.get("company_description")),
    ]
    return "\n".join(p for p in parts if p)
