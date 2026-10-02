"""
Player Injuries & Team Performance Dashboard  (FootLens Analytics)
Main Streamlit app  ->  run locally with:  streamlit run app.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import analysis as A
from data_processing import PHASE_LABELS, build_player_summary, run_pipeline

# --------------------------------------------------------------------------- #
# Page setup
# --------------------------------------------------------------------------- #
st.set_page_config(page_title="FootLens | Injury Impact Dashboard", page_icon="⚽", layout="wide")

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


def find_dataset():
    files = sorted(list(DATA_DIR.glob("*.csv")) + list(DATA_DIR.glob("*.xlsx")))
    files = [f for f in files if "cleaned" not in f.name.lower()] or files
    files.sort(key=lambda f: "injur" not in f.name.lower())
    return files[0] if files else None


st.title("⚽ Player Injuries & Team Performance Dashboard")
st.caption("FootLens Analytics · AI Research & Insights Team · How do injuries change match results and player form?")

data_file = find_dataset()
if data_file is not None:
    clean, long, report = load_from_path(str(data_file))
else:
    st.warning("No dataset found in the `data/` folder. Upload the injuries CSV to continue.")
    up = st.file_uploader("Upload player injuries CSV/XLSX", type=["csv", "xlsx"])
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
rec = A.recovery_stats(df)
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
    cs = A.club_summary(df).head(10)
    fig = px.bar(cs.sort_values("total_days_lost"), x="total_days_lost", y="club", orientation="h",
                 color="injuries", color_continuous_scale="Reds", template=TEMPLATE,
                 hover_data=["players_hit", "avg_drop"], title="Top 10 clubs by total days lost to injury")
    fig.update_layout(yaxis_title=None, xaxis_title="Days lost")
    c1.plotly_chart(fig)
    mi = A.most_injured_players(df, 10).sort_values("injuries")
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
    top = A.top_injuries_by_drop(df, by=by, n=n_top, min_cases=min_cases)
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
    rec_df = A.phase_record(sub)
    kp = A.phase_kpis(sub)
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
    tl = A.player_timeline(ldf, inj_id)
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
    mat = A.month_club_matrix(df).head(top_n)
    fig = px.imshow(mat, text_auto=True, aspect="auto", color_continuous_scale="YlOrRd", template=TEMPLATE,
                    labels=dict(x="Month", y="Club", color="Injuries"), title="Injury frequency by club and month")
    fig.update_layout(height=max(400, 28 * len(mat) + 150))
    st.plotly_chart(fig)
    stacked = mat.stack()
    if stacked.max() > 0:
        (club_hot, month_hot), val = stacked.idxmax(), stacked.max()
        busiest = A.injuries_by_month(df).sort_values("injuries", ascending=False).iloc[0]
        st.info(f"**Insight:** the biggest single cluster is **{club_hot} in {month_hot}** ({int(val)} injuries). "
                f"Across all clubs, **{busiest['month']}** is the peak month ({int(busiest['injuries'])} injuries).")
    c1, c2 = st.columns(2)
    fig = px.bar(A.injuries_by_month(df), x="month", y="injuries", template=TEMPLATE, title="Injuries by month (all clubs)",
                 color="injuries", color_continuous_scale="Oranges")
    fig.update_layout(coloraxis_showscale=False, xaxis_title=None)
    c1.plotly_chart(fig)
    cs = A.club_summary(df).head(10)
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
    s = A.age_vs_drop_stats(sc)
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
    lb = A.comeback_table(df, n=n_rows, ascending=(mode == "Biggest decline"))
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
    st.dataframe(A.pivot_pre_post(df, idx).reset_index(), hide_index=True)

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
