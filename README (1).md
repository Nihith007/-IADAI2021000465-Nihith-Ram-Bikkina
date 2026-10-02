# Do Injuries Cost Teams Matches? A Football Injury Impact Dashboard

**Live app:** https://sa-mathematics-for-ai-jk34w2urbgafg7ylmtsey3.streamlit.app/

![Dashboard preview](screenshots/dashboard_preview.png)

## About this project

When a key player gets injured, managers usually *feel* the team gets worse, but how much worse, and for which
injuries? I built this Streamlit dashboard for the FootLens Analytics scenario to put numbers on that question.

The dataset has one row per injury. For each one it records the player (club, position, age, FIFA rating), the
injury type, the dates the player went out and came back, and the result, goal difference and player rating for
the **three matches before** the injury, the **three matches missed** and the **three matches after** the return.
That structure makes it possible to compare the same team and player across the three phases.

### What the dashboard analyses

The dashboard looks at which injuries hurt the team most, how results change before, during and after a player's absence, whether players return as good as before, when and where injuries cluster across clubs and months, which clubs lose the most to injuries, and whether player age relates to the size of the performance drop.

## How the data was prepared

- Renamed the long raw column names (for example, Match1_before_injury_Player_rating became before_1_rating).
- Turned placeholders like "N.A." and blanks into real missing values.
- Converted the injury and return dates to dates and worked out how many days each injury lasted.
- Dropped duplicate rows, unreadable dates and injuries that ended before they started.
- Filled missing age and FIFA rating with the median. Missing match ratings were **not** filled in; they are skipped when averages are calculated so no values are made up.

Columns I created:

- **injury_days**: days out
- **avg_rating_before**, **avg_rating_after** and **rating_change**: the player's form around the injury
- **performance_drop_index**: the team's average goal difference before the injury minus during the absence. A positive number means the team did worse without the player.
- **ppg_before**, **ppg_during**, **ppg_after**: team points per game (win 3, draw 1, loss 0)

The data was also grouped by player to summarise the before, during and after phases, and pivot tables compare pre- and post-injury performance by position, age group and injury category.

## Features

- Six interactive Plotly charts and a leaderboard table (hover, zoom, switch options)
- Sidebar filters for season, club, position, injury category and age that update every chart
- A paired t-test on before vs after ratings, and a correlation and trend line for age vs drop
- A short plain-English takeaway under each chart
- A "Data & Cleaning" tab showing what was cleaned, plus a download button for the cleaned data

## How the pieces fit together

Everything lives in app.py, in three parts that feed each other: the raw CSV in the data folder is cleaned and extended with new columns using pandas, the analysis functions then summarise it (groupby, pivot tables and SciPy statistics), and finally Streamlit and Plotly display the results as an interactive dashboard. The cleaning result is cached with st.cache_data, so it runs once and the filters stay fast.

## Running and deploying it

To run it on your own machine, install the packages listed in requirements.txt and start the app with Streamlit using app.py as the main file.

To deploy on Streamlit Community Cloud:

1. Put app.py, requirements.txt and the data folder in a public GitHub repository.
2. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub and choose **Create app**.
3. Pick the repository, the main branch and app.py as the main file, then click **Deploy**.

## Repository contents

- **data/** – the raw dataset the app reads
- **screenshots/** – screenshots of the running app
- **app.py** – cleaning, analysis and dashboard code
- **requirements.txt** – Python packages needed
- **README.md** – this file
