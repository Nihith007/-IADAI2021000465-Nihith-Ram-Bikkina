"""
Player Injuries & Team Performance Dashboard  (FootLens Analytics)
==================================================================
Single-file Streamlit app. Run locally with:  streamlit run app.py

Sections of this file
    1. DATA PREPROCESSING & CLEANING   - load, rename, clean, engineer features, tidy match table
    2. EXPLORATORY ANALYSIS HELPERS    - one function per business question (pandas / NumPy / SciPy)
    3. DASHBOARD (Streamlit + Plotly)  - sidebar filters, KPIs and the interactive visuals
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

try:
    from scipy import stats
except Exception:  # scipy is optional - the dashboard still works without p-values
    stats = None

# Must be the first Streamlit command
st.set_page_config(page_title="FootLens | Injury Impact Dashboard", page_icon="⚽", layout="wide")

# =========================================================================== #
# SECTION 1 - DATA PREPROCESSING & CLEANING
# =========================================================================== #
# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
PHASES = ["before", "during", "after"]            # order used everywhere
PHASE_LABELS = {"before": "Before injury", "during": "During absence", "after": "After return"}

# Strings that really mean "missing"
NA_TOKENS = {"", "n.a.", "n.a", "na", "n/a", "nan", "none", "null", "-", "--"}

# Raw (normalised) column name -> readable name. First alias found wins.
BASE_ALIASES = {
    "player_name": ["name", "player", "player_name"],
    "club": ["team_name", "team", "club", "club_name"],
    "position": ["position", "pos"],
    "age": ["age"],
    "season": ["season"],
    "fifa_rating": ["fifa_rating", "fifa_ovr", "overall_rating", "rating_fifa"],
    "injury_type": ["injury", "injury_type", "injury_name"],
    "injury_start": ["date_of_injury", "injury_start", "injury_date", "start_date", "injury_start_date"],
    "injury_end": ["date_of_return", "injury_end", "return_date", "end_date", "injury_end_date"],
}
REQUIRED = ["player_name", "club", "injury_start", "injury_end"]

# e.g. match1_before_injury_player_rating
RAW_MATCH_RE = re.compile(
    r"^match_?(\d+)_(before_injury|missed_match|after_injury)_(result|opposition|gd|player_rating)$"
)
# e.g. before_1_rating (our readable name)
NEW_MATCH_RE = re.compile(r"^(before|during|after)_(\d+)_(result|opposition|gd|rating)$")
RAW_PHASE_TO_NEW = {"before_injury": "before", "missed_match": "during", "after_injury": "after"}

# Keyword -> broad injury category (first match wins, so order matters)
INJURY_CATEGORY_RULES = [
    ("Hamstring", ["hamstring"]),
    ("Knee", ["knee", "acl", "cruciate", "meniscus", "patella"]),
    ("Ankle", ["ankle"]),
    ("Groin / Hip", ["groin", "hip", "adductor", "pelvis"]),
    ("Calf / Achilles", ["calf", "achilles"]),
    ("Thigh / Muscle", ["thigh", "quad", "muscle", "strain"]),
    ("Foot", ["foot", "toe", "metatars", "heel"]),
    ("Back", ["back", "spine", "spinal"]),
    ("Shoulder / Arm", ["shoulder", "arm", "elbow", "wrist", "hand", "collarbone"]),
    ("Head", ["head", "concussion", "facial", "nose", "jaw"]),
    ("Illness", ["illness", "virus", "flu", "covid", "corona", "infection", "fever"]),
    ("Ligament / Fracture", ["ligament", "fracture", "broken", "bone"]),
]


# --------------------------------------------------------------------------- #
# 1. Loading
# --------------------------------------------------------------------------- #
def read_csv_flexible(src, filename: str = "") -> pd.DataFrame:
    """Read a CSV/XLSX from a path, bytes, or file-like object (tries several encodings)."""
    suffix = Path(filename).suffix.lower()
    if isinstance(src, (str, Path)):
        suffix = Path(src).suffix.lower()
        raw = Path(src).read_bytes()
    elif isinstance(src, (bytes, bytearray)):
        raw = bytes(src)
    else:  # Streamlit UploadedFile / file-like
        suffix = Path(getattr(src, "name", "")).suffix.lower()
        raw = src.read()

    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(io.BytesIO(raw))
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(io.StringIO(raw.decode(enc)))
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode the file. Please save it as UTF-8 CSV.")


# --------------------------------------------------------------------------- #
# 2. Column standardisation
# --------------------------------------------------------------------------- #
def _normalise(name: str) -> str:
    """'Match1_before_injury_Player_rating ' -> 'match1_before_injury_player_rating'"""
    return re.sub(r"[^0-9a-z]+", "_", str(name).strip().lower()).strip("_")


def standardise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename unclear raw column names to readable ones.

    Examples
        Name                              -> player_name
        Team Name                         -> club
        Date of Injury                    -> injury_start
        Match1_before_injury_Player_rating-> before_1_rating
        Match2_missed_match_GD            -> during_2_gd
    """
    df = df.copy()
    df.columns = [_normalise(c) for c in df.columns]

    rename = {}
    for new, aliases in BASE_ALIASES.items():
        for alias in aliases:
            if alias in df.columns and new not in rename.values():
                rename[alias] = new
                break

    for col in df.columns:
        m = RAW_MATCH_RE.match(col)
        if m:
            n, phase, field = m.groups()
            field = "rating" if field == "player_rating" else field
            rename[col] = f"{RAW_PHASE_TO_NEW[phase]}_{n}_{field}"

    df = df.rename(columns=rename)

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(
            f"Required columns not found: {missing}. Columns in file: {list(df.columns)[:25]} ..."
        )
    return df


# --------------------------------------------------------------------------- #
# 3. Cleaning helpers
# --------------------------------------------------------------------------- #
def _blank_to_nan(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace and turn placeholder strings ('N.A.', '-', '') into real NaN."""
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == object or pd.api.types.is_string_dtype(df[col]):
            s = df[col].astype("string").str.strip()
            is_na = s.str.lower().isin(NA_TOKENS).fillna(False)
            df[col] = s.mask(is_na).astype(object)
    return df


def _parse_dates(series: pd.Series) -> pd.Series:
    """Convert to datetime. Tries month-first and day-first, keeps whichever parses more rows."""
    month_first = pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=False)
    day_first = pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=True)
    return day_first if day_first.notna().sum() > month_first.notna().sum() else month_first


def _title_text(series: pd.Series) -> pd.Series:
    """Collapse repeated spaces and apply Title Case (keeps NaN as NaN)."""
    return series.astype("string").str.replace(r"\s+", " ", regex=True).str.strip().str.title().astype(object)


def _standardise_result(series: pd.Series) -> pd.Series:
    """win/won/w -> Win, lose/lost/loss/l -> Loss, draw/drawn/d -> Draw."""
    mapping = {"win": "Win", "won": "Win", "w": "Win",
               "lose": "Loss", "lost": "Loss", "loss": "Loss", "l": "Loss",
               "draw": "Draw", "drawn": "Draw", "d": "Draw", "tie": "Draw"}
    s = series.astype("string").str.strip().str.lower().map(mapping)
    return s.astype(object)


def _categorise_injury(text) -> str:
    if not isinstance(text, str):
        return "Other"
    t = text.lower()
    for category, keywords in INJURY_CATEGORY_RULES:
        if any(k in t for k in keywords):
            return category
    return "Other"


def _match_columns(df: pd.DataFrame, phase: str, field: str) -> list[str]:
    """All columns like before_1_rating, before_2_rating... sorted by match number."""
    cols = []
    for c in df.columns:
        m = NEW_MATCH_RE.match(c)
        if m and m.group(1) == phase and m.group(3) == field:
            cols.append((int(m.group(2)), c))
    return [c for _, c in sorted(cols)]


# --------------------------------------------------------------------------- #
# 3. Main cleaning function
# --------------------------------------------------------------------------- #
def clean_injury_data(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Clean the raw injury table. Returns (clean_df, report) - the report documents every step."""
    report: dict = {"steps": []}

    def log(msg: str):
        report["steps"].append(msg)

    df = standardise_columns(raw)
    # raw columns that share a name with one we create later would be silently overwritten -> keep them as source_*
    reserved = ["injury_id", "injury_days", "injury_year", "injury_month", "injury_month_name", "age_group",
                "injury_category", "severity", "star_player", "rating_change", "performance_drop_index",
                "ppg_drop", "comeback_status"]
    clash = {c: f"source_{c}" for c in reserved if c in df.columns}
    if clash:
        df = df.rename(columns=clash)
    report["raw_rows"], report["raw_columns"] = df.shape
    log(f"Loaded {df.shape[0]} rows x {df.shape[1]} columns and renamed columns to readable names.")

    # --- placeholders -> NaN, then record how much is missing -------------------------
    df = _blank_to_nan(df)
    report["missing_before"] = df.isna().sum().loc[lambda s: s > 0].sort_values(ascending=False)
    log("Replaced placeholders such as 'N.A.', '-' and blanks with proper missing values (NaN).")

    # --- duplicates ---------------------------------------------------------------------
    n = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    report["duplicates_removed"] = n - len(df)
    log(f"Removed {n - len(df)} exact duplicate rows.")

    # --- text columns -------------------------------------------------------------------
    for col in ["player_name", "club", "position", "injury_type"]:
        if col in df.columns:
            df[col] = _title_text(df[col])
    n = len(df)
    df = df.dropna(subset=["player_name", "club"]).reset_index(drop=True)
    log(f"Dropped {n - len(df)} rows with no player name or club.")
    df["position"] = df["position"].fillna("Unknown") if "position" in df.columns else "Unknown"
    df["injury_type"] = df["injury_type"].fillna("Unknown") if "injury_type" in df.columns else "Unknown"

    # --- dates --------------------------------------------------------------------------
    df["injury_start"] = _parse_dates(df["injury_start"])
    df["injury_end"] = _parse_dates(df["injury_end"])
    n = len(df)
    df = df.dropna(subset=["injury_start", "injury_end"]).reset_index(drop=True)
    report["dropped_bad_dates"] = n - len(df)
    log(f"Converted injury dates to datetime; dropped {n - len(df)} rows with unreadable/missing dates.")

    # --- invalid durations --------------------------------------------------------------
    df["injury_days"] = (df["injury_end"] - df["injury_start"]).dt.days
    n = len(df)
    df = df[df["injury_days"] >= 0].reset_index(drop=True)
    report["dropped_negative_duration"] = n - len(df)
    log(f"Removed {n - len(df)} rows where the return date was before the injury date.")

    # --- numeric columns ----------------------------------------------------------------
    for col in ["age", "fifa_rating"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            filled = int(df[col].isna().sum())
            df[col] = df[col].fillna(df[col].median())
            log(f"Filled {filled} missing '{col}' values with the median ({df[col].median():.1f}).")
        else:
            df[col] = np.nan

    # ratings: numeric, remove impossible values (<=0 or above the scale)
    rating_cols = [c for c in df.columns if NEW_MATCH_RE.match(c) and c.endswith("_rating")]
    for c in rating_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if rating_cols:
        scale_max = 10 if df[rating_cols].stack().quantile(0.99) <= 10 else 100
        bad = ((df[rating_cols] <= 0) | (df[rating_cols] > scale_max)).sum().sum()
        for c in rating_cols:
            df.loc[(df[c] <= 0) | (df[c] > scale_max), c] = np.nan
        log(f"Set {int(bad)} impossible match ratings (<=0 or >{scale_max}) to NaN.")

    # goal difference + result columns
    for c in [c for c in df.columns if NEW_MATCH_RE.match(c) and c.endswith("_gd")]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    inferred = 0
    for c in [c for c in df.columns if NEW_MATCH_RE.match(c) and c.endswith("_result")]:
        df[c] = _standardise_result(df[c])
        gd_col = c.replace("_result", "_gd")
        if gd_col in df.columns:  # infer a missing result from the sign of the goal difference
            mask = df[c].isna() & df[gd_col].notna()
            df.loc[mask, c] = np.sign(df.loc[mask, gd_col]).map({1.0: "Win", 0.0: "Draw", -1.0: "Loss"})
            inferred += int(mask.sum())
    log(f"Standardised match results to Win/Draw/Loss; inferred {inferred} missing results from goal difference.")

    # --- season label -------------------------------------------------------------------
    if "season" in df.columns and df["season"].notna().any():
        df["season"] = df["season"].astype("string").str.strip().fillna("Unknown").astype(object)
    else:
        y = df["injury_start"].dt.year
        start_year = np.where(df["injury_start"].dt.month >= 7, y, y - 1)
        df["season"] = [f"{s}/{str(s + 1)[-2:]}" for s in start_year]
        log("No season column found - derived season label from injury start date.")

    df = engineer_features(df)

    # our own row id; if the raw file already has a column with that name, keep it under a new name
    if "injury_id" in df.columns:
        df = df.rename(columns={"injury_id": "source_injury_id"})
    df.insert(0, "injury_id", range(len(df)))
    report["clean_rows"] = len(df)
    report["missing_after"] = df.isna().sum().loc[lambda s: s > 0].sort_values(ascending=False)
    log(f"Final clean dataset: {len(df)} rows. Remaining NaNs are genuine gaps (e.g. no rating recorded) "
        "and are ignored in averages rather than invented.")
    return df, report


# --------------------------------------------------------------------------- #
# 4. Feature engineering
# --------------------------------------------------------------------------- #
def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Create the analysis columns required by the brief.

    avg_rating_before / avg_rating_after / rating_change
    avg_gd_before / avg_gd_during / avg_gd_after
    performance_drop_index = avg_gd_before - avg_gd_during   (positive = team did WORSE without the player)
    ppg_*                  = points per game (Win 3, Draw 1, Loss 0) per phase
    """
    df = df.copy()

    # time features
    df["injury_year"] = df["injury_start"].dt.year
    df["injury_month"] = df["injury_start"].dt.month
    df["injury_month_name"] = df["injury_start"].dt.strftime("%b")

    # category features
    df["age_group"] = pd.cut(df["age"], bins=[0, 21, 25, 29, 33, 100],
                             labels=["<=21", "22-25", "26-29", "30-33", "34+"]).astype(object)
    df["injury_category"] = df["injury_type"].map(_categorise_injury)
    df["severity"] = pd.cut(df["injury_days"], bins=[-1, 14, 45, 90, np.inf],
                            labels=["Minor (<=14d)", "Moderate (15-45d)", "Major (46-90d)", "Severe (>90d)"]
                            ).astype(object)
    df["star_player"] = np.where(df["fifa_rating"] >= df["fifa_rating"].quantile(0.75), "Star (top 25%)", "Squad player")

    # phase averages
    for phase in PHASES:
        gd_cols = _match_columns(df, phase, "gd")
        df[f"avg_gd_{phase}"] = df[gd_cols].mean(axis=1) if gd_cols else np.nan
        res_cols = _match_columns(df, phase, "result")
        if res_cols:
            pts = df[res_cols].apply(lambda s: s.map({"Win": 3, "Draw": 1, "Loss": 0}))
            df[f"ppg_{phase}"] = pts.mean(axis=1)
            df[f"matches_{phase}"] = df[res_cols].notna().sum(axis=1)
        else:
            df[f"ppg_{phase}"] = np.nan
            df[f"matches_{phase}"] = 0
    for phase in ["before", "after"]:
        rat_cols = _match_columns(df, phase, "rating")
        df[f"avg_rating_{phase}"] = df[rat_cols].mean(axis=1) if rat_cols else np.nan

    # the key engineered metrics
    df["rating_change"] = df["avg_rating_after"] - df["avg_rating_before"]
    df["performance_drop_index"] = df["avg_gd_before"] - df["avg_gd_during"]
    df["ppg_drop"] = df["ppg_before"] - df["ppg_during"]

    # wins / draws / losses while the player was absent
    during_res = _match_columns(df, "during", "result")
    for label in ["Win", "Draw", "Loss"]:
        df[f"during_{label.lower()}s"] = (df[during_res] == label).sum(axis=1) if during_res else 0

    df["comeback_status"] = pd.cut(df["rating_change"], bins=[-np.inf, -0.2, 0.2, np.inf],
                                   labels=["Declined", "Stable", "Improved"]).astype(object)
    return df


# --------------------------------------------------------------------------- #
# 5. Long (tidy) match table - one row per match slot
# --------------------------------------------------------------------------- #
def build_match_long(df: pd.DataFrame) -> pd.DataFrame:
    """Wide -> long: injury_id, player_name, club, phase, match_no, result, opposition, gd, rating."""
    frames = []
    for phase in PHASES:
        numbers = sorted({int(NEW_MATCH_RE.match(c).group(2)) for c in df.columns
                          if NEW_MATCH_RE.match(c) and NEW_MATCH_RE.match(c).group(1) == phase})
        for n in numbers:
            part = df[["injury_id", "player_name", "club"]].copy()
            part["phase"] = phase
            part["match_no"] = n
            for field in ["result", "opposition", "gd", "rating"]:
                col = f"{phase}_{n}_{field}"
                part[field] = df[col] if col in df.columns else np.nan
            frames.append(part)
    if not frames:
        return pd.DataFrame(columns=["injury_id", "player_name", "club", "phase", "match_no",
                                     "result", "opposition", "gd", "rating"])
    long = pd.concat(frames, ignore_index=True)
    long["phase"] = pd.Categorical(long["phase"], categories=PHASES, ordered=True)
    return long.sort_values(["injury_id", "phase", "match_no"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# 6. Group by player (before / during / after summary)
# --------------------------------------------------------------------------- #
def build_player_summary(df: pd.DataFrame) -> pd.DataFrame:
    """One row per player: injuries, days lost and average performance in each injury phase."""
    summary = (
        df.groupby("player_name")
        .agg(
            club=("club", lambda s: s.mode().iat[0] if not s.mode().empty else s.iat[0]),
            position=("position", "first"),
            injuries=("injury_id", "count"),
            total_days_out=("injury_days", "sum"),
            avg_days_out=("injury_days", "mean"),
            avg_rating_before=("avg_rating_before", "mean"),
            avg_rating_after=("avg_rating_after", "mean"),
            rating_change=("rating_change", "mean"),
            avg_gd_before=("avg_gd_before", "mean"),
            avg_gd_during=("avg_gd_during", "mean"),
            avg_gd_after=("avg_gd_after", "mean"),
            avg_performance_drop=("performance_drop_index", "mean"),
        )
        .reset_index()
        .sort_values("injuries", ascending=False)
    )
    return summary.round(3)


# --------------------------------------------------------------------------- #
# One call that does everything
# --------------------------------------------------------------------------- #
def run_pipeline(src, filename: str = "") -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Load -> clean -> engineer -> long table.  Returns (clean_df, match_long_df, report)."""
    raw = src if isinstance(src, pd.DataFrame) else read_csv_flexible(src, filename)
    clean, report = clean_injury_data(raw)
    long = build_match_long(clean)
    return clean, long, report

# =========================================================================== #
# SECTION 2 - EXPLORATORY ANALYSIS HELPERS (one per business question)
# =========================================================================== #
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

# =========================================================================== #
# SECTION 3 - DASHBOARD (Streamlit + Plotly)
# =========================================================================== #
COLORS = {"Win": "#2e9e5b", "Draw": "#f2b134", "Loss": "#d9534f",
          "before": "#3b82f6", "during": "#d9534f", "after": "#2e9e5b"}
TEMPLATE = "plotly_white"
DATA_DIR = Path(__file__).parent / "data"


# --------------------------------------------------------------------------- #
# Data loading (cached so the pipeline only runs once)
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner="Cleaning data ...")
def load_from_path(path: str):
    return run_pipeline(path)


@st.cache_data(show_spinner="Cleaning data ...")
def load_from_bytes(content: bytes, name: str):
    return run_pipeline(content, filename=name)


DATA_EXTS = {".csv", ".xlsx", ".xls"}   # matched case-insensitively (so .CSV works too)


def find_dataset():
    """Look in data/ (including sub-folders), then next to app.py, for a CSV/Excel file."""
    here = Path(__file__).parent
    found = []
    if DATA_DIR.exists():
        found += [f for f in DATA_DIR.rglob("*") if f.is_file() and f.suffix.lower() in DATA_EXTS]
    found += [f for f in here.glob("*") if f.is_file() and f.suffix.lower() in DATA_EXTS]
    found = [f for f in found if "cleaned" not in f.name.lower()] or found   # prefer the RAW file
    found.sort(key=lambda f: ("injur" not in f.name.lower(), len(f.parts)))
    return found[0] if found else None


st.title("⚽ Player Injuries & Team Performance Dashboard")
st.caption("FootLens Analytics · AI Research & Insights Team · How do injuries change match results and player form?")

data_file = find_dataset()
if data_file is not None:
    clean, long, report = load_from_path(str(data_file))
else:
    st.warning("No dataset found in the `data/` folder. Upload the injuries CSV below to continue "
               "(or add it to the `data/` folder of your GitHub repo so it loads automatically).")
    with st.expander("🔧 Troubleshooting - what the app can see"):
        here = Path(__file__).parent
        st.write(f"App folder: `{here}`")
        st.write("Files in app folder:", sorted(p.name for p in here.iterdir()))
        st.write("`data/` exists:", DATA_DIR.exists())
        if DATA_DIR.exists():
            st.write("Files in `data/`:", sorted(str(p.relative_to(DATA_DIR)) for p in DATA_DIR.rglob("*")))
    up = st.file_uploader("Upload player injuries CSV/XLSX", type=["csv", "xlsx", "xls"])
    if up is None:
        st.stop()
    clean, long, report = load_from_bytes(up.getvalue(), up.name)

# --------------------------------------------------------------------------- #
# Sidebar filters
# --------------------------------------------------------------------------- #
st.sidebar.header("🎛️ Filters")
seasons = st.sidebar.multiselect("Season", sorted(clean["season"].unique()), default=sorted(clean["season"].unique()))
clubs = st.sidebar.multiselect("Club", sorted(clean["club"].unique()), placeholder="All clubs")
positions = st.sidebar.multiselect("Position", sorted(clean["position"].unique()), placeholder="All positions")
cats = st.sidebar.multiselect("Injury category", sorted(clean["injury_category"].unique()), placeholder="All categories")
age_min, age_max = int(clean["age"].min()), int(clean["age"].max())
age_rng = st.sidebar.slider("Age range", age_min, age_max, (age_min, age_max)) if age_min < age_max else (age_min, age_max)

mask = clean["season"].isin(seasons) & clean["age"].between(*age_rng)
if clubs:
    mask &= clean["club"].isin(clubs)
if positions:
    mask &= clean["position"].isin(positions)
if cats:
    mask &= clean["injury_category"].isin(cats)
df = clean[mask]
ldf = long[long["injury_id"].isin(df["injury_id"])]

if df.empty:
    st.error("No injuries match the current filters - widen your selection in the sidebar.")
    st.stop()

st.sidebar.success(f"{len(df):,} of {len(clean):,} injuries selected")
st.sidebar.download_button("⬇️ Download cleaned data (CSV)", clean.to_csv(index=False).encode(),
                           "cleaned_player_injuries.csv", "text/csv")

# --------------------------------------------------------------------------- #
# KPI row
# --------------------------------------------------------------------------- #
rec = recovery_stats(df)
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Injuries", f"{len(df):,}")
k2.metric("Players affected", f"{df['player_name'].nunique():,}")
k3.metric("Avg days out", f"{df['injury_days'].mean():.0f}")
k4.metric("Avg team performance drop", f"{df['performance_drop_index'].mean():.2f} goals",
          help="Average goal difference BEFORE the injury minus goal difference WHILE the player was out. Positive = team did worse without the player.")
k5.metric("Players rated higher after return", f"{rec.get('pct_improved', float('nan')):.0f}%")
st.divider()

tabs = st.tabs(["🏠 Overview", "1️⃣ Injury Impact", "2️⃣ Win/Loss Record", "3️⃣ Player Timeline",
                "4️⃣ Injury Clusters", "5️⃣ Age vs Drop", "6️⃣ Comebacks", "🧹 Data & Cleaning"])

# =========================================================================== #
# OVERVIEW
# =========================================================================== #
with tabs[0]:
    st.subheader("Business questions this dashboard answers")
    st.markdown(
        """
1. **Which injuries led to the biggest team performance drop?** → tab *Injury Impact* (bar chart)
2. **What was the team's win/draw/loss record during a player's absence?** → tab *Win/Loss Record*
3. **How did individual players perform after recovery?** → tabs *Player Timeline* (line chart) and *Comebacks* (leaderboard)
4. **Are there months or clubs with frequent injury clusters?** → tab *Injury Clusters* (heatmap)
5. **Which clubs suffer most due to injuries?** → tab *Injury Clusters* (club ranking)
6. **Does age influence how much the team suffers?** → tab *Age vs Drop* (scatter plot)
        """
    )
    c1, c2 = st.columns(2)
    cs = club_summary(df).head(10)
    fig = px.bar(cs.sort_values("total_days_lost"), x="total_days_lost", y="club", orientation="h",
                 color="injuries", color_continuous_scale="Reds", template=TEMPLATE,
                 hover_data=["players_hit", "avg_drop"], title="Top 10 clubs by total days lost to injury")
    fig.update_layout(yaxis_title=None, xaxis_title="Days lost")
    c1.plotly_chart(fig)
    mi = most_injured_players(df, 10).sort_values("injuries")
    fig = px.bar(mi, x="injuries", y="player_name", orientation="h", color="total_days_out",
                 color_continuous_scale="Blues", template=TEMPLATE, hover_data=["club"],
                 title="Most frequently injured players")
    fig.update_layout(yaxis_title=None, xaxis_title="Number of injuries")
    c2.plotly_chart(fig)

# =========================================================================== #
# 1. BAR - Top injuries with highest team performance drop
# =========================================================================== #
with tabs[1]:
    st.subheader("Which injuries hurt the team most?")
    c1, c2, c3 = st.columns(3)
    by = c1.radio("Group injuries by", ["injury_type", "injury_category"], horizontal=True,
                  format_func=lambda x: "Specific injury" if x == "injury_type" else "Broad category")
    n_top = c2.slider("Number of injuries to show", 3, 15, 10)
    min_cases = c3.slider("Minimum cases per injury", 1, 20, 3, help="Avoids a single unlucky match skewing the ranking.")
    top = top_injuries_by_drop(df, by=by, n=n_top, min_cases=min_cases)
    if top.empty:
        st.info("No injury has that many cases - lower the minimum.")
    else:
        fig = px.bar(top.sort_values("avg_drop"), x="avg_drop", y=by, orientation="h", color="avg_drop",
                     color_continuous_scale="Reds", template=TEMPLATE, text="avg_drop",
                     hover_data={"cases": True, "avg_ppg_drop": True, "avg_days_out": True},
                     title=f"Top {len(top)} injuries by team performance drop index")
        fig.update_layout(yaxis_title=None, xaxis_title="Avg goal-difference drop (before − during absence)",
                          coloraxis_showscale=False)
        st.plotly_chart(fig)
        worst = top.iloc[0]
        st.info(f"**Insight:** {worst[by]} injuries show the biggest drop - the team's goal difference fell by "
                f"**{worst['avg_drop']:.2f} goals per match** on average ({int(worst['cases'])} cases, "
                f"avg {worst['avg_days_out']:.0f} days out).")
        with st.expander("See the table"):
            st.dataframe(top, hide_index=True)

# =========================================================================== #
# 2. WIN / LOSS record during absence
# =========================================================================== #
with tabs[2]:
    st.subheader("Team results before, during and after a player's injury")
    pick = st.selectbox("Club", ["All clubs"] + sorted(df["club"].unique()))
    sub = ldf if pick == "All clubs" else ldf[ldf["club"] == pick]
    rec_df = phase_record(sub)
    kp = phase_kpis(sub)
    if rec_df.empty:
        st.info("No match results available for this selection.")
    else:
        rec_df["phase"] = rec_df["phase"].astype(str).map(PHASE_LABELS)
        fig = px.bar(rec_df, x="phase", y="percent", color="result", barmode="stack", text="percent",
                     color_discrete_map={k: COLORS[k] for k in ["Win", "Draw", "Loss"]}, template=TEMPLATE,
                     category_orders={"phase": list(PHASE_LABELS.values()), "result": ["Win", "Draw", "Loss"]},
                     hover_data=["matches"], title=f"Win / Draw / Loss share of matches - {pick}")
        fig.update_traces(texttemplate="%{text:.0f}%")
        fig.update_layout(xaxis_title=None, yaxis_title="% of matches")
        st.plotly_chart(fig)
        kp["phase"] = kp["phase"].astype(str).map(PHASE_LABELS)
        st.dataframe(kp.rename(columns={"phase": "Phase", "matches": "Matches", "points_per_game": "Points / game",
                                        "avg_goal_diff": "Avg goal diff"}), hide_index=True)
        b = kp.set_index("phase")
        try:
            ppg_b, ppg_d = b.loc[PHASE_LABELS["before"], "points_per_game"], b.loc[PHASE_LABELS["during"], "points_per_game"]
            st.info(f"**Insight:** points per game moved from **{ppg_b:.2f}** (before) to **{ppg_d:.2f}** (during absence) "
                    f"- a change of {ppg_d - ppg_b:+.2f} points per match.")
        except KeyError:
            pass

# =========================================================================== #
# 3. LINE - player timeline
# =========================================================================== #
with tabs[3]:
    st.subheader("Player performance timeline (before → absence → after)")
    c1, c2 = st.columns(2)
    player = c1.selectbox("Player", sorted(df["player_name"].unique()))
    p_inj = df[df["player_name"] == player].sort_values("injury_start")
    labels = {r.injury_id: f"{r.injury_type} · {r.injury_start:%d %b %Y} ({r.injury_days} days)" for r in p_inj.itertuples()}
    inj_id = c2.selectbox("Injury", list(labels), format_func=labels.get)
    tl = player_timeline(ldf, inj_id)
    row = p_inj[p_inj["injury_id"] == inj_id].iloc[0]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.6, 0.4], vertical_spacing=0.08,
                        subplot_titles=("Player match rating", "Team goal difference in the same match"))
    fig.add_trace(go.Scatter(x=tl["label"], y=tl["rating"], mode="lines+markers", name="Player rating",
                             line=dict(color="#3b82f6", width=3), marker=dict(size=10), connectgaps=False), row=1, col=1)
    if pd.notna(row["avg_rating_before"]):
        fig.add_hline(y=row["avg_rating_before"], line_dash="dash", line_color="grey", row=1, col=1,
                      annotation_text="avg before injury")
    fig.add_trace(go.Bar(x=tl["label"], y=tl["gd"], name="Goal difference",
                         marker_color=[COLORS[p] for p in tl["phase"]],
                         customdata=np.stack([tl["result"].fillna("n/a"), tl["opposition"].fillna("n/a")], axis=1),
                         hovertemplate="%{x}<br>GD: %{y}<br>%{customdata[0]} vs %{customdata[1]}<extra></extra>"),
                  row=2, col=1)
    fig.update_xaxes(categoryorder="array", categoryarray=list(tl["label"]))
    fig.update_layout(template=TEMPLATE, height=560, showlegend=False,
                      title=f"{player} - {row['injury_type']} ({row['club']})")
    st.plotly_chart(fig)
    st.caption("🔵 Before · 🔴 During absence (player not playing, so no rating) · 🟢 After return. "
               "Match numbers follow the order of the dataset columns.")
    m1, m2, m3 = st.columns(3)
    m1.metric("Avg rating before", "n/a" if pd.isna(row["avg_rating_before"]) else f"{row['avg_rating_before']:.2f}")
    m2.metric("Avg rating after", "n/a" if pd.isna(row["avg_rating_after"]) else f"{row['avg_rating_after']:.2f}",
              None if pd.isna(row["rating_change"]) else f"{row['rating_change']:+.2f}")
    m3.metric("Team performance drop", "n/a" if pd.isna(row["performance_drop_index"]) else f"{row['performance_drop_index']:.2f} goals")

# =========================================================================== #
# 4. HEATMAP - month x club
# =========================================================================== #
with tabs[4]:
    st.subheader("When and where do injuries cluster?")
    n_clubs = df["club"].nunique()
    top_n = st.slider("Number of clubs shown (most injuries first)", 1, n_clubs, min(15, n_clubs)) if n_clubs > 1 else 1
    mat = month_club_matrix(df).head(top_n)
    fig = px.imshow(mat, text_auto=True, aspect="auto", color_continuous_scale="YlOrRd", template=TEMPLATE,
                    labels=dict(x="Month", y="Club", color="Injuries"), title="Injury frequency by club and month")
    fig.update_layout(height=max(400, 28 * len(mat) + 150))
    st.plotly_chart(fig)
    stacked = mat.stack()
    if stacked.max() > 0:
        (club_hot, month_hot), val = stacked.idxmax(), stacked.max()
        busiest = injuries_by_month(df).sort_values("injuries", ascending=False).iloc[0]
        st.info(f"**Insight:** the biggest single cluster is **{club_hot} in {month_hot}** ({int(val)} injuries). "
                f"Across all clubs, **{busiest['month']}** is the peak month ({int(busiest['injuries'])} injuries).")
    c1, c2 = st.columns(2)
    fig = px.bar(injuries_by_month(df), x="month", y="injuries", template=TEMPLATE, title="Injuries by month (all clubs)",
                 color="injuries", color_continuous_scale="Oranges")
    fig.update_layout(coloraxis_showscale=False, xaxis_title=None)
    c1.plotly_chart(fig)
    cs = club_summary(df).head(10)
    fig = px.bar(cs.sort_values("avg_ppg_drop"), x="avg_ppg_drop", y="club", orientation="h", template=TEMPLATE,
                 color="avg_ppg_drop", color_continuous_scale="Reds", hover_data=["injuries", "total_days_lost"],
                 title="Which clubs suffer most? (points per game lost during absences)")
    fig.update_layout(coloraxis_showscale=False, yaxis_title=None, xaxis_title="Avg points-per-game drop")
    c2.plotly_chart(fig)

# =========================================================================== #
# 5. SCATTER - age vs drop
# =========================================================================== #
with tabs[5]:
    st.subheader("Does a player's age relate to the team's performance drop?")
    sc = df.dropna(subset=["age", "performance_drop_index"]).assign(days_size=lambda d: d["injury_days"].clip(lower=1))
    color_by = st.radio("Colour by", ["position", "star_player", "severity", "age_group"], horizontal=True)
    fig = px.scatter(sc, x="age", y="performance_drop_index", color=color_by, size="days_size", size_max=18,
                     hover_name="player_name", hover_data=["club", "injury_type", "injury_days"], template=TEMPLATE,
                     opacity=0.75, title="Player age vs team performance drop index (bubble size = days injured)")
    s = age_vs_drop_stats(sc)
    if "slope" in s:
        xs = np.array([sc["age"].min(), sc["age"].max()])
        fig.add_trace(go.Scatter(x=xs, y=s["intercept"] + s["slope"] * xs, mode="lines", name="Linear trend",
                                 line=dict(color="black", dash="dash")))
    fig.update_layout(xaxis_title="Age", yaxis_title="Performance drop index (goals)")
    st.plotly_chart(fig)
    if "r" in s:
        p_txt = f", p = {s['p_value']:.3f}" if "p_value" in s else ""
        strength = "weak" if abs(s["r"]) < 0.3 else "moderate" if abs(s["r"]) < 0.6 else "strong"
        direction = "positive" if s["r"] > 0 else "negative"
        st.info(f"**Statistics:** Pearson r = **{s['r']:.2f}** (R² = {s['r2']:.3f}{p_txt}) → a **{strength} {direction}** "
                f"relationship. Each extra year of age is associated with a {s['slope']:+.3f} goal change in the drop index.")
    st.markdown("**Average by age group**")
    st.dataframe(df.groupby("age_group").agg(injuries=("injury_id", "count"), avg_days_out=("injury_days", "mean"),
                                             avg_drop=("performance_drop_index", "mean"),
                                             avg_rating_change=("rating_change", "mean")).round(2).reset_index(),
                 hide_index=True)

# =========================================================================== #
# 6. LEADERBOARD - comeback players
# =========================================================================== #
with tabs[6]:
    st.subheader("Comeback leaderboard - rating improvement after injury")
    c1, c2 = st.columns(2)
    n_rows = c1.slider("Players to show", 5, 50, 15)
    mode = c2.radio("Show", ["Biggest improvement", "Biggest decline"], horizontal=True)
    lb = comeback_table(df, n=n_rows, ascending=(mode == "Biggest decline"))
    st.dataframe(
        lb, hide_index=True,
        column_config={
            "rank": st.column_config.NumberColumn("#", width="small"),
            "player_name": "Player", "club": "Club", "position": "Position", "age": "Age",
            "injury_type": "Injury", "injury_days": st.column_config.NumberColumn("Days out"),
            "avg_rating_before": st.column_config.NumberColumn("Rating before", format="%.2f"),
            "avg_rating_after": st.column_config.NumberColumn("Rating after", format="%.2f"),
            "rating_change": st.column_config.NumberColumn("Change", format="%+.2f"),
        },
    )
    st.markdown("#### Recovery statistics")
    if rec.get("n", 0) > 0:
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Avg rating before", f"{rec['mean_before']:.2f}")
        r2.metric("Avg rating after", f"{rec['mean_after']:.2f}", f"{rec['mean_change']:+.2f}")
        r3.metric("Improved after return", f"{rec['pct_improved']:.0f}%")
        r4.metric("Effect size (Cohen's d)", f"{rec['cohens_d']:.2f}" if pd.notna(rec.get("cohens_d")) else "n/a")
        if "p_value" in rec:
            verdict = "statistically significant" if rec["p_value"] < 0.05 else "not statistically significant"
            st.info(f"**Paired t-test:** t = {rec['t_stat']:.2f}, p = {rec['p_value']:.3f} → the before/after rating "
                    f"difference is **{verdict}** at the 5% level (n = {rec['n']}).")
    st.markdown("#### Pivot table - pre vs post-injury performance")
    idx = st.selectbox("Compare by", ["position", "age_group", "injury_category", "severity", "star_player", "club"])
    st.dataframe(pivot_pre_post(df, idx).reset_index(), hide_index=True)

# =========================================================================== #
# DATA & CLEANING
# =========================================================================== #
with tabs[7]:
    st.subheader("Data preprocessing report")
    a, b, c = st.columns(3)
    a.metric("Raw rows", report["raw_rows"])
    b.metric("Clean rows", report["clean_rows"])
    c.metric("Rows removed", report["raw_rows"] - report["clean_rows"])
    st.markdown("**Cleaning steps applied**")
    for step in report["steps"]:
        st.markdown(f"- {step}")
    m1, m2 = st.columns(2)
    m1.markdown("**Missing values - before cleaning**")
    m1.dataframe(report["missing_before"].rename("missing").reset_index().rename(columns={"index": "column"}), hide_index=True)
    m2.markdown("**Missing values - after cleaning**")
    m2.dataframe(report["missing_after"].rename("missing").reset_index().rename(columns={"index": "column"}), hide_index=True)

    st.markdown("**Engineered columns**")
    st.markdown(
        """
| Column | Meaning |
|---|---|
| `injury_days` | Days between injury start and return |
| `avg_rating_before` / `avg_rating_after` | Mean player rating in the matches before the injury / after return |
| `rating_change` | `avg_rating_after − avg_rating_before` |
| `avg_gd_before` / `avg_gd_during` / `avg_gd_after` | Mean team goal difference in each phase |
| **`performance_drop_index`** | `avg_gd_before − avg_gd_during` (positive = team did worse without the player) |
| `ppg_before` / `ppg_during` / `ppg_after`, `ppg_drop` | Points per game (Win 3, Draw 1, Loss 0) |
| `injury_category`, `severity`, `age_group`, `star_player` | Readable groupings for filters and pivots |
        """
    )
    st.markdown("**Player summary (grouped by player: before / during / after)**")
    st.dataframe(build_player_summary(df), hide_index=True)
    st.markdown("**Cleaned data preview**")
    st.dataframe(df.head(100), hide_index=True)
