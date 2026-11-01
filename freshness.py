import pandas as pd


def filter_by_evaluated_hours(df: pd.DataFrame, max_hours: int | None) -> pd.DataFrame:
    """Keep rows whose scraped_at is within the last max_hours (UTC)."""
    if df.empty or not max_hours or max_hours <= 0:
        return df
    if "scraped_at" not in df.columns:
        return df

    scraped = pd.to_datetime(df["scraped_at"], utc=True, errors="coerce")
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=max_hours)
    mask = scraped.notna() & (scraped >= cutoff)
    return df.loc[mask].copy()
