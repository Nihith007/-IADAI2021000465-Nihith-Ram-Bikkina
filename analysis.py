"""
analysis.py
===========
Step 3: EXPLORATORY DATA ANALYSIS helpers (pure pandas / numpy / scipy).
Each function answers one of the project's business questions and is reused by app.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    from scipy import stats
except Exception:  # scipy is optional - the dashboard still works without p-values
    stats = None

MONTH_ORDER = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# Q1 - Which injuries led to the biggest team performance drop?
def top_injuries_by_drop(df: pd.DataFrame, by: str = "injury_type", n: int = 10, min_cases: int = 1) -> pd.DataFrame:
    out = (
        df.dropna(subset=["performance_drop_index"])
        .groupby(by)
        .agg(cases=("injury_id", "count"),
             avg_drop=("performance_drop_index", "mean"),
             avg_ppg_drop=("ppg_drop", "mean"),
             avg_days_out=("injury_days", "mean"))
        .reset_index()
    )
    out = out[out["cases"] >= min_cases].sort_values("avg_drop", ascending=False).head(n)
    return out.round(2)


# Q2 - What was the team's win/draw/loss record during player absence?
def phase_record(long: pd.DataFrame) -> pd.DataFrame:
    """Win/Draw/Loss counts, % and points-per-game for before / during / after phases."""
    d = long.dropna(subset=["result"])
    counts = d.groupby(["phase", "result"], observed=True).size().unstack(fill_value=0)
    for col in ["Win", "Draw", "Loss"]:
        if col not in counts:
            counts[col] = 0
    counts = counts[["Win", "Draw", "Loss"]]
    total = counts.sum(axis=1)
    pct = counts.div(total, axis=0) * 100
    out = pct.round(1).reset_index().melt(id_vars="phase", var_name="result", value_name="percent")
    out = out.merge(counts.reset_index().melt(id_vars="phase", var_name="result", value_name="matches"),
                    on=["phase", "result"])
    return out


def phase_kpis(long: pd.DataFrame) -> pd.DataFrame:
    d = long.dropna(subset=["result"]).copy()
    d["points"] = d["result"].map({"Win": 3, "Draw": 1, "Loss": 0})
    return (d.groupby("phase", observed=True)
            .agg(matches=("result", "count"), points_per_game=("points", "mean"), avg_goal_diff=("gd", "mean"))
            .round(2).reset_index())


# Q3 - How did players perform after recovery?
def recovery_stats(df: pd.DataFrame) -> dict:
    d = df.dropna(subset=["avg_rating_before", "avg_rating_after"])
    out = {"n": len(d)}
    if d.empty:
        return out
    diff = d["rating_change"]
    out.update(
        mean_before=d["avg_rating_before"].mean(),
        mean_after=d["avg_rating_after"].mean(),
        mean_change=diff.mean(),
        median_change=diff.median(),
        std_change=diff.std(ddof=1) if len(d) > 1 else np.nan,
        pct_improved=(diff > 0).mean() * 100,
        cohens_d=(diff.mean() / diff.std(ddof=1)) if len(d) > 1 and diff.std(ddof=1) > 0 else np.nan,
    )
    if stats is not None and len(d) > 2:  # paired t-test: is the before/after difference real?
        t, p = stats.ttest_rel(d["avg_rating_after"], d["avg_rating_before"])
        out.update(t_stat=t, p_value=p)
    return out


def comeback_table(df: pd.DataFrame, n: int = 20, ascending: bool = False) -> pd.DataFrame:
    cols = ["player_name", "club", "position", "age", "injury_type", "injury_days",
            "avg_rating_before", "avg_rating_after", "rating_change"]
    d = df.dropna(subset=["rating_change"])[cols].sort_values("rating_change", ascending=ascending).head(n)
    d = d.round(2).reset_index(drop=True)
    d.insert(0, "rank", d.index + 1)
    return d


def pivot_pre_post(df: pd.DataFrame, index: str) -> pd.DataFrame:
    return (df.pivot_table(index=index,
                           values=["avg_rating_before", "avg_rating_after", "rating_change", "performance_drop_index"],
                           aggfunc="mean")
            .round(2)
            .sort_values("rating_change", ascending=False))


# Q4 - Months / clubs with injury clusters
def month_club_matrix(df: pd.DataFrame) -> pd.DataFrame:
    m = df.pivot_table(index="club", columns="injury_month_name", values="injury_id",
                       aggfunc="count", fill_value=0)
    m = m.reindex(columns=[c for c in MONTH_ORDER if c in m.columns], fill_value=0)
    return m.loc[m.sum(axis=1).sort_values(ascending=False).index]


def injuries_by_month(df: pd.DataFrame) -> pd.DataFrame:
    s = df["injury_month_name"].value_counts().reindex(MONTH_ORDER).fillna(0).astype(int)
    return s.rename_axis("month").reset_index(name="injuries")


# Q5 - Which clubs suffer most?
def club_summary(df: pd.DataFrame) -> pd.DataFrame:
    return (df.groupby("club")
            .agg(injuries=("injury_id", "count"),
                 players_hit=("player_name", "nunique"),
                 total_days_lost=("injury_days", "sum"),
                 avg_drop=("performance_drop_index", "mean"),
                 avg_ppg_drop=("ppg_drop", "mean"))
            .round(2).reset_index().sort_values("total_days_lost", ascending=False))


def most_injured_players(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    return (df.groupby(["player_name", "club"])
            .agg(injuries=("injury_id", "count"), total_days_out=("injury_days", "sum"))
            .reset_index().sort_values(["injuries", "total_days_out"], ascending=False).head(n))


# Q6 - Age vs performance drop
def age_vs_drop_stats(df: pd.DataFrame) -> dict:
    d = df.dropna(subset=["age", "performance_drop_index"])
    out = {"n": len(d)}
    if len(d) < 3 or d["age"].nunique() < 2:
        return out
    slope, intercept = np.polyfit(d["age"], d["performance_drop_index"], 1)
    r = np.corrcoef(d["age"], d["performance_drop_index"])[0, 1]
    out.update(slope=slope, intercept=intercept, r=r, r2=r ** 2)
    if stats is not None:
        out["p_value"] = stats.pearsonr(d["age"], d["performance_drop_index"])[1]
    return out


# Player timeline (line chart)
def player_timeline(long: pd.DataFrame, injury_id: int) -> pd.DataFrame:
    t = long[long["injury_id"] == injury_id].copy()
    t["phase"] = t["phase"].astype(str)
    t["label"] = t["phase"].str.capitalize() + " " + t["match_no"].astype(str)
    return t.reset_index(drop=True)
