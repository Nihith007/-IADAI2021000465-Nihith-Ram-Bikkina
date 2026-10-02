"""
data_processing.py
==================
Step 2 of the project: DATA PREPROCESSING & CLEANING.

Everything that touches raw data lives here so that app.py stays focused on the
dashboard. The module can also be run on its own:

    python data_processing.py --input data/player_injuries_impact.csv \
                              --output data/cleaned_player_injuries.csv

Pipeline (each step is its own small function):
    1. read_csv_flexible()      load CSV/XLSX safely (encoding fallback)
    2. standardise_columns()    rename unclear columns -> readable snake_case
    3. clean_injury_data()      missing values, dates, types, outliers, duplicates
    4. engineer_features()      rating before/after, team performance drop index...
    5. build_match_long()       wide match columns -> tidy long table (for charts)
    6. build_player_summary()   group by player: before / during / after stats
"""
from __future__ import annotations

import argparse
import io
import re
from pathlib import Path

import numpy as np
import pandas as pd

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


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Clean the player-injury dataset.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", default="data/cleaned_player_injuries.csv")
    args = ap.parse_args()

    clean_df, _, rep = run_pipeline(args.input)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    clean_df.to_csv(args.output, index=False)
    print("\n".join(f" - {s}" for s in rep["steps"]))
    print(f"\nSaved {len(clean_df)} cleaned rows to {args.output}")
